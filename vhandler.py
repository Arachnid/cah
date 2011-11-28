import uuid
# import webapp2
# from webapp2_extras import jinja2
from ndb import model
import logging

from google.appengine.api import channel
from google.appengine.ext import deferred

import models
import base

# task method
def calculate_and_send_scores(game_key):
  # for all active participants, calculate everyone's scores, based on
  # yet-to-be-defined metrics.  This is run in a task.
  # does it need to be in a txn?
  game = game_key.get()
  def _txn():
    participants = models.Participant.query(
        models.Participant.playing == True,
        ancestor=game.key).fetch()
    for p in participants:
      # tbd: actual calculation
      p.score = random.randint(1,10)
    model.put_multi(participants)
  model.transaction(_tx)
  _send_scores(participants)

def _send_scores(participants):
  # tbd
  for participant in participants:
    message = "particpant %s got score %s" % (participant.key, participant.score)
    logging.info("score message to %s: %s" % (participant, message))
    channel.send_message(
        participant.channel_id, message)

class VoteHandler(base.BaseHandler):

  
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
    game = models.Hangout.get_current_game(hangout_id)
    if not game:
      self.render_jsonp({'status': 'ERROR', 
        'message' : "Game for hangout %s not found" % (hangout_id,)})
      return
    else:
      # check game state.
      # players can only vote from 'start_round' or 'voting' state.
      # if in start_round state, a vote effects transition to 'voting' state
      if not (game.state == 'start_round' or game.state == 'voting'):
        self.render_jsonp({'status' : 'ERROR', 'message': "Can't vote now."})
        return
    # game state is okay to proceed
    try:
      pvid = self.request.GET['pvote'] # the id of the player being voted for
      plus_id = self.request.GET['plus_id'] # the id of the player submitting 
          #the vote
      # logging.info("game key: %s", game.key)
      participant_key = model.Key(models.Participant, plus_id, parent=game.key)
      # logging.info("participant_key: %s", participant_key)                                
      participant = participant_key.get()
    except:
      self.render_jsonp(
          {'status': 'ERROR', 'message': "Voting info incomplete"})
      return
    if not participant:
      self.render_jsonp(
          {'status': 'ERROR', 'message': "Could not retrieve indicated participant"})      
      return
    # otherwise, record the vote
    # TODO : also check that entity exists for this participant key?
    vpkey = model.Key(models.Participant, pvid, parent=game.key)
    
    def _tx():
      participant.vote = vpkey
      if game.state == 'start_round':
        game.state = 'voting'
      else: # in voting state already
        # check to see if we have all the votes
        if self.all_votesp(game):
          # then transition to scoring state
          game.state = 'scores'

      model.put_multi([game, participant])
      if game.state == 'scores':
        # then spawn txnal task to calculate the scores and send them to the
        # clients via their channels
        deferred.defer(calculate_and_send_scores, game.key)

    model.transaction(_tx)

    # We can now start a new round.  If we've had N rounds, this is a new 
    # game instead.  
    # Can this be pushed to a task as well?
    if game.current_round == models.ROUNDS_PER_GAME:
      # then start new game using the participants of the current game
      self.start_new_game(hangout_id)
    else:
      # otherwise, start new round in the current game
      self.start_new_round(game.key)

    self.render_jsonp({'status': 'OK'})

  def start_new_round(self, game_key):
    # tbd.  
    # should probably be transactional    
    # will need to include setting the participant's votes for the current
    # round to 'none'
    pass

  def start_new_game(self, hangout_id):
    # tbd.
    # should probably be transactional
    pass


