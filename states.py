from ndb import model
import logging

from google.appengine.api import channel, memcache

import config
import models

try:
  import json as simplejson
except ImportError:
  from django.utils import simplejson

# logging.getLogger().setLevel(logging.DEBUG)

# This class and its subclasses are an attempt to make the state transition
# logic used by the app more explicit (but not fully declarative).  This code
# works; however still playing around with the general approach-- this may
# not be the final design

# Currently, the card selection state and the voting state are implemented
# as subclasses.
# Currently, the transitions are not ambiguous, i.e. there is a
# non-intersecting set of transition conditions from a state to each of its
# its next states.


class GameState(object):
  """
  A base class for the 'game states'. 
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
    to transition to the given next state.  Should return True if conditions
    met, False if not.
    """
    raise NotImplementedError(
        "_check_transit_conds() not implemented in %s" % self)

  def _make_transit(self, next_state, **kwargs):
    """Should be implemented by the subclass-- makes the transition to the
    specified next state.  Should return True if transition successful, 
    False if not.
    """
    raise NotImplementedError("make_transit() not implemented in %s" % self)

  def try_transition(self, next_state, **kwargs):
    """Transition (if conditions are met) to the given next_state if next state
    arg is set;  otherwise (no specific next_state indicated)
    to a next state whose transition conditions are met. make_transit should
    return True if transition made; False, if error while
    making transition.  try_transition returns None if no transition tried
    (no conditions met).
    """
    # Note: wrapping the entire transition, including its condition checking,
    # in a transaction.  This is overkill under many circumstances (so we might
    # want to change this if there are contention issues), and also takes
    # advantage of the fact that currently everything we need to operate on
    # is in the same entity group, but makes the semantics of the
    # implementation more clear.

    def _tx():
      res = None
      if next_state:  # if state specified, try to transit to it
        if self._check_transit_conds(next_state, **kwargs):
          res = self._make_transit(next_state, **kwargs)
      else:
        for ns in self.next_states:
          # take the first transition whose conditions are met
          if self._check_transit_conds(ns, **kwargs):
            res = self._make_transit(ns, **kwargs)
            logging.info("finished make_transit with res %s", res)
            break
      return res
    resp = model.transaction(_tx)  # run the transaction
    return resp

  # this key-generation method (for memcache storage) is used by > 1 subclass
  def _selections_key(self, game_id, curr_round):
    return "%s:%s:selections" % (game_id, curr_round)


class GameStateFactory(object):
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
    Returns a boolean.
    If the next state is 'voting', and the 'action' argument is 'vote', then it
    is always okay to transition. (a user can vote more than once as long
    as the game is still in the 'voting' state; the last vote is retained).
    If the next state is 'scores', then transition conditions are met if all
    participants have voted.
    """
    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    if next_state == self.state_name:
      return kwargs['action']  == 'vote'
    elif next_state == 'scores': # okay to transition if all participants
        # have voted
      return self.all_votesp(game.key)
    else:
      return False

  def _make_transit(self, next_state, **kwargs):
    """Perform the transition to the given next state.  Returns a boolean:
    True if transition was successful, False if not.
    """
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
    logging.info(
            "participants who have not voted: %s", 
            [p.plus_id for p in participants])
    if participants:
      return False
    else:
      return True

  def _get_pid_from_selcard(self, card_id):
    """..."""

    # (re)build entire memcache selections list, then return info for
    # requested card. The participants' selected
    # cards are for the current round.
    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    skey = self._selections_key(game.key.id(), game.current_round)
    selections = {}
    participants = game.participants()
    for p in participants:
      if p.selected_card:
        selections[p.selected_card] = p.plus_id
    logging.info("in _get_pid_from_selcard, got selections list %s",
                 selections)
    memcache.set(skey, selections)
    return selections.get(card_id)

  # performed if the action is 'vote', as indicated above in
  # _check_transit_conds
  def _transit_to_voting(self, **kwargs):
    """Transition from the 'voting' state to itself (via the 'vote' action).
    Once placed, a vote will not be unset from this 'voting' state,
    though it could be overridden with another vote from the same person
    before all votes are in (which is okay)
    """

    handler = kwargs['handler']

    plus_id = kwargs['plus_id']
    card_id = kwargs['card_id']
    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    if not game:
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': "Game for hangout %s not found" % (self.hangout_id,)})
      return False
    if not game.state == self.state_name:
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': (
                 "Can't vote now, wrong game state %s." % (game.state,))})
      return False      
    # try to get the id of the voted-for player based on their selected card
    # via memcache first.
    selections = memcache.get(
        self._selections_key(game.key.id(), game.current_round))
    if selections:  # if cache hit
      logging.info("got selections cache hit: %s", selections)
      pvid = selections.get(card_id)
      if not pvid:
        # cache list was present, but not info for that card
        pvid = self._get_pid_from_selcard(card_id)
    else:  # cache miss on selections list
      logging.info("did not get selections cache hit")
      pvid = self._get_pid_from_selcard(card_id)
    logging.debug("in _transit_to_voting, with plus id %s and pvid %s",
                  plus_id, pvid)
    if not plus_id or not pvid:
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': 'Voting information not properly specified'})
      return False
    if plus_id == pvid:
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': 'Participants cannot vote for themselves.'})
      return False

    participant_key = model.Key(models.Participant, plus_id, parent=game.key)
    participant = participant_key.get()
    if not participant:
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': "Could not retrieve indicated participant"})
      return False
    # TODO: also check that entity exists for given participant key
    vpkey = model.Key(models.Participant, pvid, parent=game.key)
    participant.vote = vpkey
    participant.put()
    return True

  # performed if all participants have voted, as indicated above in
  # _check_transit_conds
  def _transit_to_scores(self, **kwargs):
    """Transition from the 'voting' state to the 'scores' state.
    """
    logging.debug("in _transit_to_scores")
    handler = kwargs['handler']

    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    if not game:
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': "Game for hangout %s not found" % (self.hangout_id,)})
      return False
    if game.state != self.state_name:
      return False  # not in 'voting' state
    game.state = 'scores'
    participants = self._calculate_scores(game)
    game.put()
    # send out the score info on the channels.
    # TODO: currently, the scores for this round are only recorded briefly,
    # as the code below will reset them as part of the setup for the
    # next round/game.  Might want to change this.
    # TODO: should the broadcasting part be part of the handler logic or
    # the state transition logic?
    self._broadcast_scores(participants, game.key.id(), game.current_round)

    # We can now start a new round.  This resets the card selection and vote
    # fields.  If we've had N rounds, this is a new game instead.  
    if game.current_round >= (config.ROUNDS_PER_GAME - 1):
      # if have reached the limit of rounds for a game,
      # then start new game using the participants of the current game
      self.start_new_game(participants)
      return True
    else:
      # otherwise, start new round in the current game
      logging.info("starting new round.")
      game.start_new_round(participants)
      return True

  def start_new_game(self, participants):
    logging.info("starting new game.")
    new_game = models.Hangout.start_new_game(self.hangout_id, participants)
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
      # accumulate game score and hangout_score with this round's results.
      p.game_score += p.score
      p.hangout_score += p.score
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

  def _broadcast_scores(self, participants, game_id, round_num):
    """ broadcast the scores for the current round as well as the running game
    score thus far for each participant.
    """
    pscores = {}
    for p in participants:
      pscores[p.plus_id] = (
          {'score': p.score, 'game_score': p.game_score,
           'hangout_score': p.hangout_score})
    message = simplejson.dumps(
        {'scores_info':
         {'participant_scores': pscores, 'game_id': game_id,
          'round': round_num}})
    logging.info("scores message: %s", message)
    for p in participants:
      logging.info("sending channel msg to participant %s", p.plus_id)
      channel.send_message(p.channel_id, message)


# ----------------------------------------


class StartRoundGameState(GameState):
  """ In the 'start_round' state, each participant selects an answer card
  from their hand.
  """

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
    if next_state == self.state_name:
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
  def _transit_to_start_round(self, **kwargs):
    """From the start_round state, transition to the start_round state.
    """
    logging.info("in _transit_to_start_round")
    handler = kwargs['handler']

    # Once placed, a vote will not be unset from within this 'voting' state,
    # though it could be overridden with another vote from the same person
    # before all votes are in (which is okay)
    plus_id = kwargs['plus_id']
    selected_card = kwargs['card_num']

    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    if not game:
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': "Game for hangout %s not found" % (self.hangout_id,)})
      return False
    else:
      logging.debug("using game: %s", game)
      # check game state.
      # players can only select a card from the 'start_round' state.
      if not game.state == self.state_name:
        if handler:
          handler.render_jsonp(
              {'status' : 'ERROR',
               'message': (
                   "Can't vote now, wrong game state %s." % (game.state,))})
        return False
    participant_key = model.Key(models.Participant, plus_id, parent=game.key)
    participant = participant_key.get()
    if not participant:
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': "Could not retrieve indicated participant"})
      return False
    sres = participant.select_card(selected_card)
    participant.put()
    if sres is None:  # need to check explicitly, b/c of card 0
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': "could not select card %s from hand" % selected_card})
      return False

    # broadcast successful selection by player, but don't indicate the
    # card selected.  (After all have selected, the shuffled set of
    # selections will be broadcast)
    self._cache_selection(
        plus_id, selected_card, game.key.id(),
        game.current_round)
    message = simplejson.dumps({'player_selection': 
               {'participant': plus_id,
                'game_id': game.key.id(),
                'round': game.current_round}})
    logging.info("player selection channel msg: %s", message)
    participants = game.participants()
    for p in participants:
      logging.info("sending channel msg to %s", p.plus_id)
      channel.send_message(p.channel_id, message)
    
    return True

  # performed if all participants have selected a card, as indicated in
  # _check_transit_conds
  def _transit_to_voting(self, **kwargs):
    """From the start_round state, transition to the voting state.
    """
    logging.debug("in _transit_to_voting")
    handler = kwargs['handler']

    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    if not game:
      if handler:
        handler.accumulate_response(
            {'status': 'ERROR',
             'message': "Game for hangout %s not found" % (self.hangout_id,)})
      return False
    if game.state != self.state_name:
      logging.info("game state %s not valid", game.state)
      return False
    game.state = 'voting'
    game.put()
    return True

  def _cache_selection(self, plus_id, selected_card, game_id, curr_round):
    """..."""

    mkey = self._selections_key(game_id, curr_round)
    selections = memcache.get(mkey)
    if not selections:
      selections = {}
    selections[selected_card] = plus_id
    memcache.set(mkey, selections)


