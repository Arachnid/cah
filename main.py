import uuid
import webapp2
from webapp2_extras import jinja2
from ndb import model
import logging

from google.appengine.api import channel

import models
import vhandler

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
    try:
      cb = self.request.GET['callback']
    except:
      cb = ""
    # self.response.write("%s(%s);" % (self.request.GET['callback'],
    self.response.write("%s(%s);" % (cb,
                                     simplejson.dumps(response)))


class JoinGameHandler(BaseHandler):
  def get(self):
    hangout_id = self.request.GET['hangout_id']
    game = models.Hangout.get_current_game(hangout_id)
    plus_id = self.request.GET['plus_id']
    participant = models.Participant.get_participant(game, plus_id)
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


application = webapp2.WSGIApplication([
    ('/api/join_game', JoinGameHandler),
    ('/api/vote', vhandler.VoteHandler),
    ('/api/send_message', SendMessageHandler),
], debug=True)
