import uuid
import webapp2
from webapp2_extras import jinja2

from google.appengine.api import channel

import models

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


class NewGameHandler(BaseHandler):
  def get(self):
    hangout_id = self.request.GET['hangout_id']
    game = models.Game.get_or_insert(hangout_id)
    plus_id = self.request.GET['plus_id']
    participant = models.Participant.get_participant(game, plus_id)
    response = {
      'channel_token': participant.channel_token,
    }
    self.render_jsonp(response)


class SendMessageHandler(BaseHandler):
  def get(self):
    hangout_id = self.request.GET['hangout_id']
    message = self.request.GET['message']
    game = models.Game.get_or_insert(hangout_id)
    participants = models.Participant.query(ancestor=game.key).fetch()
    for participant in participants:
      channel.send_message(participant.channel_id, message)


application = webapp2.WSGIApplication([
    ('/api/join_game', NewGameHandler),
    ('/api/send_message', SendMessageHandler),
], debug=True)
