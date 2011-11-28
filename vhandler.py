
from ndb import model
import logging
import random

from google.appengine.api import channel
from google.appengine.ext import deferred

import models
import base


class SelectionHandler(base.BaseHandler):
  pass
  

class VoteHandler(base.BaseHandler):

  def calculate_and_send_scores(self, game_key):
    # for all active participants, calculate everyone's scores, based on
    # yet-to-be-defined metrics. 
    # TODO: does this need to be in a txn?
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

  def all_votesp(self, game):
    """returns a boolean, indicating whether all active game participants have
    registered a vote for this round.
    """
    participants = models.Participant.query(
      models.Participant.playing == True,
      models.Participant.vote == None,
      ancestor=game.key).fetch()
    logging.info("partipants who have not voted: %s", participants)
    if participants:
      return False
    else:
      return True
  
  def get(self):

    try:
      hangout_id = self.request.GET['hangout_id']
    except:
      self.render_jsonp({'status': 'ERROR', 
        'message' : "Hangout ID not given."})
      return

    # game state is okay to proceed
    try:
      pvid = self.request.GET['pvote'] # the id of the player being voted for
      plus_id = self.request.GET['plus_id'] # the id of the player submitting 
          #the vote
    except:
      self.render_jsonp(
          {'status': 'ERROR', 'message': "Vote data incomplete"})
      return
    

    #Once placed, a vote will not be unset from within this 'voting' state,
    # though it could be overridden with another vote from the same person
    # before all votes are in (which is okay)
    def _tx():
      game = models.Hangout.get_by_id(hangout_id).current_game.get()
      if not game:
        return {'status': 'ERROR', 
            'message' : "Game for hangout %s not found" % (hangout_id,)}
      else:
        logging.info("using game: %s", game)
        # check game state.
        # players can only vote from the 'voting' state.
        # This state is transitioned to from the 'start_round' state once everyone
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
    if not isinstance(resp, models.Game):  # then error message
      self.render_jsonp(resp)
      return
    game = resp

    # next, check to see if we have all the votes
    if self.all_votesp(game):
      # then transition to scoring state
      logging.info("all votes are in; moving to 'scores' state.")
      game.state = 'scores'
      game.put()
      # TODO - at this point, any or all of the following could potentially
      # be done in tasks, allowing the initial response to be returned
      # sooner.  Would this make sense?
      self.calculate_and_send_scores(game.key)
      # We can now start a new round.  If we've had N rounds, this is a new 
      # game instead.  
      if game.current_round >= models.ROUNDS_PER_GAME:
        # then start new game using the participants of the current game
        self.start_new_game(hangout_id)
      else:
        # otherwise, start new round in the current game
        self.start_new_round(game)

    self.render_jsonp({'status': 'OK'})

  def start_new_round(self, game):
    logging.info("starting new round.")
    game.start_new_round()
    pass

  def start_new_game(self, hangout_id):
    logging.info("starting new game.")
    new_game = models.Hangout.start_new_game(hangout_id)
    logging.info("in start_new_game, got new game: %s", new_game)


