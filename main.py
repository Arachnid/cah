import uuid
import webapp2
from webapp2_extras import jinja2
from ndb import model
import logging

from google.appengine.api import channel

import models
import states

try:
  import json as simplejson
except ImportError:
  from django.utils import simplejson


class BaseHandler(webapp2.RequestHandler):
  @webapp2.cached_property
  def jinja2(self):
    return jinja2.get_jinja2(app=self.app)

  def render_template(self, filename, **template_args):
    body = self.jinja2.render_template(filename, **template_args)
    self.response.write(body)

  def render_jsonp(self, response):
    self.response.write("%s(%s);" % (self.request.GET['callback'],
                                     simplejson.dumps(response)))


class JoinGameHandler(BaseHandler):
  def get(self):
    hangout_id = self.request.GET['hangout_id']
    game = models.Hangout.get_current_game(hangout_id)
    plus_id = self.request.GET['plus_id']
    # now, add the participant and in the process, deal their hand from
    # the game cards. 
    participant = models.Participant.get_or_create_participant(
        game.key, plus_id)
    logging.info("created participant: %s", participant)
    response = {
      'channel_token': participant.channel_token,
    }
    self.render_jsonp(response)


class LeaveGameHandler(BaseHandler):
  def get(self):
    hangout_id = self.request.GET['hangout_id']
    plus_id = self.request.GET['plus_id']
    channel_token = self.request.GET['channel_token']
    participant_key = model.Key(models.Game, hangout_id,
                                models.Participant, plus_id)
    participant = participant_key.get()
    if participant.channel_token == channel_token:
      # Remove user from game
      participant.playing = False
      participant.put()
      self.render_jsonp({'status': 'OK'})
    else:
      self.render_jsonp({'status': 'Error'})


class SendMessageHandler(BaseHandler):
  def get(self):
    hangout_id = self.request.GET['hangout_id']
    message = self.request.GET['message']
    game = models.Game.get_or_insert(hangout_id)
    participants = models.Participant.query(
        models.Participant.playing == True,
        ancestor=game.key).fetch()
    for participant in participants:
      channel.send_message(participant.channel_id, message)
    self.render_jsonp({'status': 'OK'})

# -------------------------    

class VoteHandler(BaseHandler):
  """..."""

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
            "Can't vote now, wrong game state '%s'." % (game.state,))})
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
    gs = states.GameStateFactory.get_game_state('voting', hangout_id)
    logging.info("about to attempt state transition")
    # make any valid transition
    res = gs.try_transition(
        None, action=self.ACTION, plus_id=plus_id, pvid=pvid, handler=self)
    logging.info("result of try_transition: %s", res)
    # now, see if we can do internal transition to 'scores'.
    res = gs.try_transition('scores', plus_id=plus_id, pvid=pvid, handler=self)
    logging.info("result of try_transition: %s", res)
    self.render_jsonp({'status': 'OK'})


class SelectCardHandler(BaseHandler):
  """..."""

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
            "Can't select card now, wrong game state '%s'." % (game.state,))})
      return

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
    res = gs.try_transition(
        None, action=self.ACTION, plus_id=plus_id, card_num=card_number,
        handler=self)
    logging.info("result of try_transition: %s", res)
    # now, see if we can do internal transition to 'scores'.
    res = gs.try_transition(
        'voting', plus_id=plus_id, card_num=card_number, handler=self)
    logging.info("result of try_transition: %s", res)
    self.render_jsonp({'status': 'OK'})


# -------------------------    


application = webapp2.WSGIApplication([
    ('/api/join_game', JoinGameHandler),
    ('/api/vote', VoteHandler),
    ('/api/select_card', SelectCardHandler),
    ('/api/send_message', SendMessageHandler),
], debug=True)
