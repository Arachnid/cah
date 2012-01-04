
from ndb import model
import logging
import random

from google.appengine.api import channel

import models

try:
  import json as simplejson
except ImportError:
  from django.utils import simplejson

# logging.getLogger().setLevel(logging.DEBUG)

# This class and its subclasses are an attempt to make the state transition
# logic used by the app more explicit (but not fully declarative).  [This works;
# however still playing around with the general approach-- this may not be
# the final design].

# Currently, the card selection state and the voting state are implemented
# as subclasses.
# Currently, the transitions are not ambiguous, i.e. there is a 
# non-intersecting set of transition conditions from a state to each of its
# its next states.


class GameState():

  """
  A base class for the 'game states'.  (Somewhat experimental-- see above).
  
  Each subclass must encode information about the names of the states that it 
  can transition to, how to check that the transition conditions are met for
  each such next state, and how to make the transition to each next state.
  Then, the try_transition method tries to transit to a specific next state when
  specified, and otherwise (if the next state is not specified), transits to
  the first 'next state' it finds, whose transition conditions are met.
  """

  def __init__(self, hangout_id):
    self.hangout_id = hangout_id
    self.next_states = None  # set by subclasses

  def _check_transit_conds(self, next_state, **kwargs):
    """should be implemented by the subclass-- checks whether conditions are met
    to transition to the given next state
    """
    raise NotImplementedError(
      "_check_transit_conds() not implemented in %s" % self)

  def _make_transit(self, next_state, **kwargs):
    """Should be implemented by the subclass-- makes the transition to the 
    specified next state.
    """
    raise NotImplementedError("make_transit() not implemented in %s" % self)

  def try_transition(self, next_state, **kwargs):
    """Transition (if conditions are met) to the given next_state if next state
    arg is set;  otherwise (no specific next_state indicated) 
    to a next state whose transition conditions are met.
    """
    res = None
    if next_state: # if state specified, try to transit to it
      if self._check_transit_conds(next_state, **kwargs):
        res = self._make_transit(next_state, **kwargs)
    else:
      for ns in self.next_states:
        # take the first transition whose conditions are met
        if self._check_transit_conds(ns, **kwargs):
          res = self._make_transit(ns, **kwargs)
          break
    # logging.info("in try_transition, result was: %s", res)
    return res


class GameStateFactory():
  """Generate a GameState subclass according to the given state name."""

  @classmethod
  def get_game_state(cls, state_name, hangout_id):
    if state_name == 'voting':
      return VotingGameState(hangout_id)
    if state_name == 'start_round':
      return StartRoundGameState(hangout_id)
    else:
      return None

# ----------------------------------------

class VotingGameState(GameState):
  """Encodes information about the 'voting' state.  
  """

  def __init__(self, hangout_id):
    GameState.__init__(self, hangout_id)
    self.state_name = 'voting'
    self.next_states = ['voting', 'scores']

  def _check_transit_conds(self, next_state, **kwargs):
    """Encodes transition conditions for the 'voting' state to the given next
    state.
    If the next state is 'voting', and the 'action' argument is 'vote', then it 
    is always okay to transition. (a user can vote more than once as long
    as the game is still in the 'voting' state; the last vote is retained).
    If the next state is 'scores', then transition conditions are met if all
    participants have voted.
    """
    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    if next_state == 'voting':
      return kwargs['action']  == 'vote'
    elif next_state == 'scores': # okay to transition if all participants
        # have voted
      return self.all_votesp(game.key)
    else:
      return False    

  def _make_transit(self, next_state, **kwargs):
    """Perform the transition to the given next state."""
    if next_state == 'voting':
      return self._transit_to_voting(**kwargs)
    elif next_state == 'scores':
      return self._transit_to_scores(**kwargs)
    else:
      return False    

  
  def all_votesp(self, game_key):
    """returns a boolean, indicating whether all active game participants have
    registered a vote. (vote info gets reset at the end of each round).
    """
    participants = models.Participant.query(
      models.Participant.playing == True,
      models.Participant.vote == None,
      ancestor=game_key).fetch()
    logging.info("partipants who have not voted: %s", participants)
    if participants:
      return False
    else:
      return True
  

  # performed if the action is 'vote', as indicated above in 
  # _check_transit_conds
  # (make this more explicit?)
  def _transit_to_voting(self, **kwargs):
    """Transition from the 'voting' state to itself (via the 'vote' action).
    """
    handler = kwargs['handler']
    
    # Once placed, a vote will not be unset from this 'voting' state,
    # though it could be overridden with another vote from the same person
    # before all votes are in (which is okay)
    plus_id = kwargs['plus_id']
    pvid = kwargs['pvid']
    logging.debug("in _transit_to_voting, with plus id %s and pvid %s",
        plus_id, pvid)
    if not plus_id or not pvid:
      if handler:
        handler.render_jsonp({'status': 'ERROR', 
              'message': 'Participant information not fully specified.'})
      return False
    if plus_id == pvid:
      if handler:
        handler.accumulate_response({'status': 'ERROR', 
              'message': 'Participants cannot vote for themselves.'})
      return False
    def _tx(): # do the transition w/in a transaction
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      if not game:
        if handler:
          handler.accumulate_response({'status': 'ERROR', 
            'message' : "Game for hangout %s not found" % (self.hangout_id,)})
        return False
      else:
        logging.debug("using game: %s", game)
        # check game state first within transaction.
        # players can only vote from the 'voting' state.
        # (This state is transitioned to from the 'start_round' state once 
        # everyone has selected their cards and the selections have been 
        # displayed to all the players).
        if not game.state == 'voting':
          if handler:
            handler.accumulate_response({'status' : 'ERROR', 
                  'message': (
                      "Can't vote now, wrong game state %s." % (game.state,))})
          return False
      participant_key = model.Key(models.Participant, plus_id, parent=game.key)
      participant = participant_key.get()
      if not participant:
        if handler:
          handler.accumulate_response({'status': 'ERROR', 
           'message': "Could not retrieve indicated participant"})
        return False
      # TODO : also check that entity exists for given participant key?
      vpkey = model.Key(models.Participant, pvid, parent=game.key)
      participant.vote = vpkey
      participant.put()
      return game
    
    resp = model.transaction(_tx)  # run the transaction
    return resp

  # performed if all participants have voted, as indicated above in
  # _check_transit_conds
  # (make this more explicit?)
  def _transit_to_scores(self, **kwargs):
    """Transition from the 'voting' state to the 'scores' state.
    """
    logging.debug("in _transit_to_scores")
    handler = kwargs['handler']
    
    def _tx(): # effect the state change in a transaction
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      if not game:
        if handler:
          handler.accumulate_response({'status': 'ERROR', 
            'message' : "Game for hangout %s not found" % (self.hangout_id,)})
        return False
      if game.state != 'voting':
        return False
      game.state = 'scores'
      participants = self._calculate_scores(game)
      game.put()
      # send out the score info on the channels.  This could be done in a
      # transactional task instead.
      # TODO: currently, the scores for this round are only recorded briefly,
      # as the transaction below will reset them as part of the setup for the 
      # next round/game.  Might want to change this.
      # TODO: should the broadcasting part be part of the handler logic or 
      # the state transition logic?
      self._broadcast_scores(participants)
      return True
    model.transaction(_tx)
    # We can now start a new round.  If we've had N rounds, this is a new 
    # game instead.  This resets the card selection and vote fields.
    def _tx2():
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      if game.current_round >= models.ROUNDS_PER_GAME:
        # if have reached the limit of rounds for a game,
        # then start new game using the participants of the current game
        return (game, self.start_new_game())
      else:
        # otherwise, start new round in the current game
        return (self.start_new_round(game), None)      
    game, new_game = model.transaction(_tx2)
    return True

  def start_new_round(self, game):
    logging.info("starting new round.")
    game.start_new_round()
    return game
    

  def start_new_game(self):
    logging.info("starting new game.")
    new_game = models.Hangout.start_new_game(self.hangout_id)
    logging.info("in start_new_game, got new game: %s", new_game)
    return new_game
 
  def _calculate_scores(self, game):
    # for all active participants, calculate everyone's scores, based on
    # yet-to-be-defined metrics. As a strawman method, just set a score for each
    # participant based upon how many others voted for that person.

    participants = game.participants()
    pvotes = self._build_votes_dict(participants)
    for p in participants:
      p.score = pvotes.get(p.plus_id, 0)
      # accumulate game score with this round's results
      p.game_score += p.score
    model.put_multi(participants)
    return participants
  

  def _build_votes_dict(self, participants):
    """
    Accumulate the votes for each participant from the other participants
    for this round.
    """
    # more idiomatic way to do this?
    pvotes = {}
    for p in participants:
      pid = p.vote.id()
      pvcount = pvotes.get(pid, 0)
      pvotes[pid] = pvcount + 1
    logging.info("in _build_votes_dict, got pvotes: %s", pvotes)
    return pvotes

  # TODO: should probably send list rather than multiple messages
  # TODO: should the broadcasting part be part of the handler logic or the
  # state transition logic?
  def _broadcast_scores(self, participants):
    for participant in participants:
      message = ("particpant %s got score %s" 
                 % (participant.key.id(), participant.score))
      for p in participants:
        logging.info("score message to %s: %s" % (p.key, message))
        channel.send_message(
            p.channel_id, message)


# ----------------------------------------

class StartRoundGameState(GameState):

  def __init__(self, hangout_id):
    GameState.__init__(self, hangout_id)
    self.state_name = 'start_round'
    self.next_states = ['start_round', 'voting']

  def _make_transit(self, next_state, **kwargs):
    if next_state == 'start_round':
      return self._transit_to_start_round(**kwargs)
    elif next_state == 'voting':
      return self._transit_to_voting(**kwargs)
    else:
      return False

  def _check_transit_conds(self, next_state, **kwargs):
    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    if next_state == 'start_round':
      return kwargs['action']  == 'select_card'
    elif next_state == 'voting': # this internal state change will be
        # explicitly requested
      return self.all_cards_selected(game.key)
    else:
      return False      

  # transition condition to 'scores'
  def all_cards_selected(self, game_key):
    """returns a boolean, indicating whether all active game participants have
    selected a card for this round.
    """
    participants = models.Participant.query(
      models.Participant.playing == True,
      models.Participant.selected_card == None,
      ancestor=game_key).fetch()
    logging.debug("participants who have not selected a card: %s", participants)
    if participants:
      return False
    else:
      return True
  
  # performed if the action is 'select_card', as indicated in 
  # _check_transit_conds
  # (make this more explicit?)
  def _transit_to_start_round(self, **kwargs):
    """From the start_round state, transition to the start_round state.
    """
    logging.info("in _transit_to_start_round")
    handler = kwargs['handler']
    
    #Once placed, a vote will not be unset from within this 'voting' state,
    # though it could be overridden with another vote from the same person
    # before all votes are in (which is okay)
    plus_id = kwargs['plus_id']
    def _tx():
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      if not game:
        if handler:
          handler.accumulate_response(
              {'status': 'ERROR', 
               'message' : "Game for hangout %s not found" % (self.hangout_id,)})
        return False
      else:
        logging.debug("using game: %s", game)
        # check game state.
        # players can only select a card from the 'start_round' state.
        if not game.state == 'start_round':
          if handler:
            handler.render_jsonp({'status' : 'ERROR', 
                  'message': (
                      "Can't vote now, wrong game state %s." % (game.state,))})
          return False
      participant_key = model.Key(models.Participant, plus_id, parent=game.key)
      participant = participant_key.get()
      if not participant:
        if handler:
          handler.accumulate_response({'status': 'ERROR', 
           'message': "Could not retrieve indicated participant"})
        return False
      selected_card = kwargs['card_num']
      sres = participant.select_card(selected_card)
      participant.put()
      if not sres:
        if handler:
          handler.accumulate_response(
              {'status': 'ERROR', 
               'message': "could not select card %s from hand" % (selected_card,)})
        return False
      else:
        return selected_card
    
    res = model.transaction(_tx)  # run the transaction
    if res: #broadcast successful selection
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      message = {'selected_card': res, 'player': plus_id}
      game.message_all_participants(simplejson.dumps(message))
    return res

  # performed if all participants have selected a card, as indicated in 
  # _check_transit_conds
  # (make this more explicit?)
  def _transit_to_voting(self, **kwargs):
    """From the start_round state, transition to the voting state.
    """      
    logging.debug("in _transit_to_voting")
    handler = kwargs['handler']
    
    def _tx(): # make the state change in a transaction
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      if not game:
        if handler:
          handler.accumulate_response({'status': 'ERROR', 
            'message' : "Game for hangout %s not found" % (self.hangout_id,)})
        return False
      if game.state != 'start_round':
        logging.info("game state %s not valid", game.state)
        return
      game.state = 'voting'
      game.put()
      return game
    game = model.transaction(_tx)
    return game    
  




         


    
  

