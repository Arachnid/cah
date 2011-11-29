
from ndb import model
import logging
import random

from google.appengine.api import channel
# from google.appengine.ext import deferred

import models


class GameState():

  
  # ... assume the transitions are not ambiguous- non-intersecting set of transition conditions.
  # in that case, for each next state, can check its defined conditions, and take the first transition
  # whose conditions are met...

  def __init__(self, hangout_id):
    self.hangout_id = hangout_id
    self.next_states = None  # set by subclasses

  def check_transit(self, next_state, **kwargs):
    raise NotImplementedError("check_transit() not implemented in %s" % self)

  def make_transit(self, next_state, **kwargs):
    raise NotImplementedError("make_transit() not implemented in %s" % self)

  def attempt_transition(self, next_state, **kwargs):
    res = None
    if next_state: # if state specified, try to transit to it
      if self.check_transit(next_state, **kwargs):
        res = self.make_transit(next_state, **kwargs)
    else:
      for ns in self.next_states:
        # take the first transition whose conditions are met
        if self.check_transit(ns, **kwargs):
          res = self.make_transit(ns, **kwargs)
          break
    # logging.info("in attempt_transition, result was: %s", res)
    return res


class GameStateFactory():

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

  def __init__(self, hangout_id):
    GameState.__init__(self, hangout_id)
    self.state_name = 'voting'
    self.next_states = ['voting', 'scores']

  # transition condition to 'scores'
  def all_votesp(self, game_key):
    """returns a boolean, indicating whether all active game participants have
    registered a vote for this round.
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
  
  def check_transit(self, next_state, **kwargs):
    # logging.info("in %s check_transit", self)
    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    if next_state == 'voting':
      return kwargs['action']  == 'vote'
    elif next_state == 'scores': # this internal state change will be
        # explicitly requested
      return self.all_votesp(game.key)
    else:
      return False

  def _transit_to_scores(self):
    logging.info("in _transit_to_scores")
    
    def _tx(): # make the state change in a transaction
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      if not game:
        return {'status': 'ERROR', 
            'message' : "Game for hangout %s not found" % (self.hangout_id,)}
      if game.state != 'voting':
        return
      game.state = 'scores'
      game.put()
      # We can now start a new round.  If we've had N rounds, this is a new 
      # game instead.  
      if game.current_round >= models.ROUNDS_PER_GAME:
        # then start new game using the participants of the current game
        return (game, self.start_new_game())
      else:
        # otherwise, start new round in the current game
        return (self.start_new_round(game), None)
    game, new_game = model.transaction(_tx)

    self.calculate_and_send_scores(game.key)
    return True

  # encodes the 'vote' action.  Need to make this explicit
  def _transit_to_voting(self, **kwargs):
    logging.info("in _transit_to_voting")
    # TODO - double check correct starting state?
    
    #Once placed, a vote will not be unset from within this 'voting' state,
    # though it could be overridden with another vote from the same person
    # before all votes are in (which is okay)
    plus_id = kwargs['plus_id']
    pvid = kwargs['pvid']
    def _tx():
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      if not game:
        return {'status': 'ERROR', 
            'message' : "Game for hangout %s not found" % (self.hangout_id,)}
      else:
        logging.info("using game: %s", game)
        # check game state.
        # players can only vote from the 'voting' state.
        # This state is transitioned to from the 'start_round' state once 
        # everyone
        # has selected their cards and the selections have been displayed to
        # all the players.
        if not game.state == 'voting':
          return {'status' : 'ERROR', 
                  'message': (
                      "Can't vote now, wrong game state %s." % (game.state,))}
      participant_key = model.Key(models.Participant, plus_id, parent=game.key)
      participant = participant_key.get()
      if not participant:
        return {'status': 'ERROR', 
           'message': "Could not retrieve indicated participant"}
      # TODO : also check that entity exists for this participant key?
      vpkey = model.Key(models.Participant, pvid, parent=game.key)
      participant.vote = vpkey
      participant.put()
      return game
    
    resp = model.transaction(_tx)  # run the transaction
    if not isinstance(resp, models.Game):
      # then error
      pass
    else:
      # okay
      logging.info("in _transit_to_voting, successfully updated info")
      pass
    return resp
  
  def make_transit(self, next_state, **kwargs):
    # logging.info("in %s make_transit to next_state %s", self, next_state)

    if next_state == 'voting':
      return self._transit_to_voting(**kwargs)
    elif next_state == 'scores':
      return self._transit_to_scores()
    else:
      return False


  def start_new_round(self, game):
    logging.info("starting new round.")
    game.start_new_round()
    return game
    

  def start_new_game(self):
    logging.info("starting new game.")
    new_game = models.Hangout.start_new_game(self.hangout_id)
    logging.info("in start_new_game, got new game: %s", new_game)
    return new_game
 
  def calculate_and_send_scores(self, game_key):
    # for all active participants, calculate everyone's scores, based on
    # yet-to-be-defined metrics. 
    game = game_key.get()
    def _tx():
      participants = models.Participant.query(
          models.Participant.playing == True,
          ancestor=game.key).fetch()
      for p in participants:
        # tbd: actual calculation
        p.score = random.randint(1,10)
      model.put_multi(participants)
      return participants
    participants = model.transaction(_tx)
    self._send_scores(participants)

  def _send_scores(self, participants):
    # tbd
    for participant in participants:
      message = ("particpant %s got score %s" 
                 % (participant.key, participant.score))
      logging.info("score message to %s: %s" % (participant, message))
      channel.send_message(
          participant.channel_id, message)


# ----------------------------------------

class StartRoundGameState(GameState):

  def __init__(self, hangout_id):
    GameState.__init__(self, hangout_id)
    self.state_name = 'start_round'
    self.next_states = ['start_round', 'voting']

  # transition condition to 'scores'
  def all_cards_selected(self, game_key):
    """returns a boolean, indicating whether all active game participants have
    selected a card for this round.
    """
    participants = models.Participant.query(
      models.Participant.playing == True,
      models.Participant.selected_card == None,
      ancestor=game_key).fetch()
    logging.info("participants who have not selected a card: %s", participants)
    if participants:
      return False
    else:
      return True
  
  def check_transit(self, next_state, **kwargs):

    game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
    if next_state == 'start_round':
      return kwargs['action']  == 'select_card'
    elif next_state == 'voting': # this internal state change will be
        # explicitly requested
      return self.all_cards_selected(game.key)
    else:
      return False

  def _transit_to_voting(self):
    logging.info("in _transit_to_voting")
    
    def _tx(): # make the state change in a transaction
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      if not game:
        return {'status': 'ERROR', 
            'message' : "Game for hangout %s not found" % (self.hangout_id,)}
      if game.state != 'start_round':
        logging.info("game state %s not valid", game.state)
        return
      game.state = 'voting'
      game.put()
      # We can now start a new round.  If we've had N rounds, this is a new 
      # game instead.  
      # if game.current_round >= models.ROUNDS_PER_GAME:
      #   # then start new game using the participants of the current game
      #   return (game, self.start_new_game())
      # else:
      #   # otherwise, start new round in the current game
      #   return (self.start_new_round(game), None)
    game = model.transaction(_tx)

    # self.calculate_and_send_scores(game.key)
    return True

  # encodes the 'answer card selection' action.  Need to make this explicit.
  def _transit_to_start_round(self, **kwargs):
    logging.info("in _transit_to_start_round")
    # TODO - double check correct starting state?
    
    #Once placed, a vote will not be unset from within this 'voting' state,
    # though it could be overridden with another vote from the same person
    # before all votes are in (which is okay)
    plus_id = kwargs['plus_id']
    def _tx():
      game = models.Hangout.get_by_id(self.hangout_id).current_game.get()
      if not game:
        return {'status': 'ERROR', 
            'message' : "Game for hangout %s not found" % (self.hangout_id,)}
      else:
        logging.info("using game: %s", game)
        # check game state.
        # players can only select a card from the 'start_round' state.
        if not game.state == 'start_round':
          return {'status' : 'ERROR', 
                  'message': (
                      "Can't vote now, wrong game state %s." % (game.state,))}
      participant_key = model.Key(models.Participant, plus_id, parent=game.key)
      participant = participant_key.get()
      if not participant:
        return {'status': 'ERROR', 
           'message': "Could not retrieve indicated participant"}
      selected_card = kwargs['card_num']
      participant.select_card(selected_card)
      participant.put()
      return game
    
    resp = model.transaction(_tx)  # run the transaction
    if not isinstance(resp, models.Game):
      # then error
      pass
    else:
      # okay
      logging.info("in _transit_to_start_round, successfully updated info")
      pass
    return resp
  
  def make_transit(self, next_state, **kwargs):
    # logging.info("in %s make_transit to next_state %s", self, next_state)

    if next_state == 'start_round':
      return self._transit_to_start_round(**kwargs)
    elif next_state == 'voting':
      return self._transit_to_voting()
    else:
      return False


  def start_new_round(self, game):
    logging.info("starting new round.")
    game.start_new_round()
    return game
    

  def start_new_game(self):
    logging.info("starting new game.")
    new_game = models.Hangout.start_new_game(self.hangout_id)
    logging.info("in start_new_game, got new game: %s", new_game)
    return new_game
 
  # def calculate_and_send_scores(self, game_key):
  #   # for all active participants, calculate everyone's scores, based on
  #   # yet-to-be-defined metrics. 
  #   game = game_key.get()
  #   def _tx():
  #     participants = models.Participant.query(
  #         models.Participant.playing == True,
  #         ancestor=game.key).fetch()
  #     for p in participants:
  #       # tbd: actual calculation
  #       p.score = random.randint(1,10)
  #     model.put_multi(participants)
  #     return participants
  #   participants = model.transaction(_tx)
  #   self._send_scores(participants)

  # def _send_scores(self, participants):
  #   # tbd
  #   for participant in participants:
  #     message = ("particpant %s got score %s" 
  #                % (participant.key, participant.score))
  #     logging.info("score message to %s: %s" % (participant, message))
  #     channel.send_message(
  #         participant.channel_id, message)             


    
  

