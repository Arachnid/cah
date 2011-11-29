
from ndb import model
import logging
import random

# from google.appengine.api import channel
# from google.appengine.ext import deferred

import models
import base
import states


class VoteHandler(base.BaseHandler):

  ACTION = 'vote'
      
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
    if not game.state == 'voting':
       self.render_jsonp({'status' : 'ERROR', 
          'message': (
            "Can't vote now, wrong game state %s." % (game.state,))})

    # game state is okay to proceed
    try:
      pvid = self.request.GET['pvote'] # the id of the player being voted for
      plus_id = self.request.GET['plus_id'] # the id of the player submitting 
        #the vote
    except:
      self.render_jsonp(
        {'status': 'ERROR', 'message': "Vote data incomplete"})
      return
    gs = states.GameStateFactory.get_game_state('voting', hangout_id)
    logging.info("about to attempt state transition")
    # make any valid transition
    res = gs.attempt_transition(
        None, action=self.ACTION, plus_id=plus_id, pvid=pvid)
    logging.info("result of attempt_transition: %s", res)
    # now, see if we can do internal transition to 'scores'.
    res = gs.attempt_transition('scores', plus_id=plus_id, pvid=pvid)
    logging.info("result of attempt_transition: %s", res)
    self.render_jsonp({'status': 'OK'})


class SelectCardHandler(base.BaseHandler):

  ACTION = 'select_card'
      
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
    if not game.state == 'start_round':
       self.render_jsonp({'status' : 'ERROR', 
          'message': (
            "Can't select card now, wrong game state %s." % (game.state,))})

    # game state is okay to proceed
    try:
      plus_id = self.request.GET['plus_id'] # the id of the player selecting 
        # the card
      card_number = int(self.request.GET['card_num']) # the card number
    except:
      self.render_jsonp(
        {'status': 'ERROR', 'message': "Card selection data incomplete"})
      return
    gs = states.GameStateFactory.get_game_state('start_round', hangout_id)
    logging.info("about to attempt state transition")
    # make any valid transition
    res = gs.attempt_transition(
        None, action=self.ACTION, plus_id=plus_id, card_num=card_number)
    logging.info("result of attempt_transition: %s", res)
    # now, see if we can do internal transition to 'scores'.
    res = gs.attempt_transition('voting', plus_id=plus_id, card_num=card_number)
    logging.info("result of attempt_transition: %s", res)
    self.render_jsonp({'status': 'OK'})




