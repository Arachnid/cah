import uuid
import random
import webapp2
from webapp2_extras import jinja2
from ndb import model
import logging

from google.appengine.api import channel

import models
import states
import cards

try:
  import json as simplejson
except ImportError:
  from django.utils import simplejson

class BaseHandler(webapp2.RequestHandler):
  """ Base request handler. """

  @webapp2.cached_property
  def jinja2(self):
    return jinja2.get_jinja2(app=self.app)

  def render_template(self, filename, **template_args):
    body = self.jinja2.render_template(filename, **template_args)
    self.response.write(body)

  def render_jsonp(self, response):
    self.response.write("%s(%s);" % (self.request.GET['callback'],
                                     simplejson.dumps(response)))

  def accumulate_response(self, rdict):
    """ builds a message dict (to be returned to the client as json).
    """
    # TODO - the idea was that different stages of processing could
    # contribute different info to the dict; though currently it's not really
    # necessary to do this.
    try:
      if not hasattr(self, 'resp'):
        self.resp = rdict
      else:
        self.resp.update(rdict)
    except (AttributeError, TypeError):
      logging.info("bad dict data: %s", rdict)

  def render_jresp(self):
    if hasattr(self, 'resp') and self.resp:
      self.render_jsonp(self.resp)


class JoinGameHandler(BaseHandler):
  """ Handles a request to join the current game.  Players can join at any
  time.
  """

  def get(self):
    hangout_id = self.request.GET['hangout_id']
    game = models.Hangout.get_current_game(hangout_id)
    plus_id = self.request.GET['plus_id']
    # add the participant, and in the process, deal their hand from
    # the game cards.
    participant = models.Participant.get_or_create_participant(
        game.key, plus_id)
    logging.info("created participant: %s", participant)
    # TODO - might need to return more info here eventually.
    response = {
        'cards': participant.cards,
        'game_id': game.key.id(),
        'channel_token': participant.channel_token,
    }
    self.render_jsonp(response)


class LeaveGameHandler(BaseHandler):
  """ Handles reqeusts to leave the current game."""

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
      self.render_jsonp({'status': 'ERROR'})


class SendMessageHandler(BaseHandler):
  """ Send a message via the channel API to all participants.
  """

  def get(self):
    hangout_id = self.request.get('hangout_id')
    message = self.request.get('message')
    if not (hangout_id and message):
      self.render_jsonp({'status': 'OK'})
      return
    game = models.Game.get_or_insert(hangout_id)
    participants = models.Participant.query(
        models.Participant.playing == True,
        ancestor=game.key).fetch()
    for participant in participants:
      channel.send_message(participant.channel_id, message)
    self.render_jsonp({'status': 'OK'})


class CardMappingHandler(BaseHandler):
  """ Send the client the card deck list info, so card numbers can be mapped
  to their text client-side.
  """
  # it should be sufficient just to pass the json-ified arrays.
  def get(self):
    deck = self.request.get('deck')
    if not deck:
      self.render_jsonp(
          {'status': 'ERROR',
           'message': 'Deck not specified.'})
      return
    if deck == 'answers':
      self.render_jsonp(cards.answers)
    elif deck == 'questions':
      self.render_jsonp(cards.questions)
    else:
      self.render_jsonp(
          {'status': 'ERROR',
           'message': 'Unknown deck %s' % deck})


# ------------------------------------------
# The following two handlers make use of the GameState classes, with most
# of the state transition logic pushed to the state classes.


class VoteHandler(BaseHandler):
  """ Register a player's vote for an answer.  Voting can only happen while the
  game is in the 'voting' state, which will be the case until all players have
  voted. Players cannot vote for themselves. They can change their vote while
  the game is in the 'voting' state.
  """

  # TODO - deal with timeouts, e.g. re: some active players not voting within a
  # reasonable period of time.

  ACTION = 'vote'
  STATE = 'voting'

  def get(self):

    hangout_id = self.request.get('hangout_id')

    if not hangout_id:
      self.render_jsonp(
          {'status': 'ERROR',
           'message': "Hangout ID not given."})
      return
    game = models.Hangout.get_current_game(hangout_id)
    if not game:
      self.render_jsonp(
          {'status': 'ERROR',
           'message' : "Game for hangout %s not found" % (hangout_id,)})
      return
    if not game.state == self.STATE:
      self.render_jsonp(
          {'status' : 'ERROR',
           'message': (
               "Can't vote now, wrong game state '%s'." % (game.state,))})
      return
    # game state is okay to proceed
    try:
      card_id = int(self.request.get('card_num'))  # the number of the card
          # being voted for
    except ValueError:
      card_id = None
    plus_id = self.request.get('plus_id')  # the id of the player submitting
        # the vote
    if card_id is None or (not plus_id):
      self.render_jsonp(
          {'status': 'ERROR', 'message': "Voting data incomplete"})
      return
    # create a 'voting' game state.
    gs = states.GameStateFactory.get_game_state(self.STATE, hangout_id)
    # logging.info("about to attempt state transition")
    # the 'None' arg indicates that it's okay to make any valid transition based
    # on the given action ('vote')
    res1 = gs.try_transition(
        None, action=self.ACTION, plus_id=plus_id,
        card_id=card_id, handler=self)
    logging.info("result of try_transition on action %s: %s", self.ACTION, res1)
    # now, see if we can do internal transition to 'scores'. (no action)
    res2 = gs.try_transition('scores', plus_id=plus_id,
                             card_id=card_id, handler=self)
    logging.info("result of try_transition to 'scores': %s", res2)
    if res1 == False or res2 == False:
      # if False, then there was some issue; return the response we have
      # accumulated while processing the transition, which will give error info.
      self.render_jresp()
    else:
      self.accumulate_response({'status': 'OK'})
      self.render_jresp()


class SelectCardHandler(BaseHandler):
  """ Process a player's answer card selection. This can only occur from the
  'start_round' state. A player can't select more than one card.
  """

  ACTION = 'select_card'
  STATE = 'start_round'

  def _broadcast_selected_cards(self, game):
    participants = game.participants()
    selected = [p.selected_card for p in participants]
    random.shuffle(selected)
    msg = {'selected_cards': selected, 'game_id': game.key.id(),
           'round': game.current_round}
    game.message_all_participants(simplejson.dumps(msg))

  def get(self):

    hangout_id = self.request.get('hangout_id')
    if not hangout_id:
      self.render_jsonp(
          {'status': 'ERROR',
           'message': "Hangout ID not given."})
      return
    game = models.Hangout.get_current_game(hangout_id)
    if not game:
      self.render_jsonp(
          {'status': 'ERROR',
           'message': "Game for hangout %s not found" % (hangout_id,)})
      return
    if not game.state == self.STATE:
      self.render_jsonp(
          {'status': 'ERROR',
           'message': (
               "Can't select card now, wrong game state '%s'." % (game.state))})
      return

    # game state is okay to proceed
    plus_id = self.request.get('plus_id')  # the id of the player selecting
        # the card
    if not plus_id:
      self.render_jsonp(
          {'status': 'ERROR', 'message': "Card selection data incomplete"})
      return
    try:
      card_number = int(self.request.get('card_num')) # the card number
    except ValueError:
      self.render_jsonp(
          {'status': 'ERROR',
           'message': "Card number is not an integer"})
      return
    gs = states.GameStateFactory.get_game_state(self.STATE, hangout_id)
    # logging.info("about to attempt state transition")
    # the 'None' arg indicates that it's okay to make any valid transition based
    # on the given action ('select_card')
    selected_p = gs.try_transition(
        None, action=self.ACTION, plus_id=plus_id, card_num=card_number,
        handler=self)
    logging.info(
        "result of try_transition with action %s: %s",
        self.ACTION, selected_p)
    # now, see if we can do internal transition to 'voting'. (no action)
    voting_p = gs.try_transition(
        'voting', plus_id=plus_id, card_num=card_number, handler=self)
    logging.info("result of try_transition to 'voting': %s", voting_p)

    if selected_p == False or voting_p == False:
      # if False, then there was some issue; return the response we have
      # accumulated while processing the transition, which will give error info.
      self.render_jresp()
    else:  # no errors
      if voting_p:  # if transition to voting
        # broadcast the set of selected cards to everyone
        self._broadcast_selected_cards(game)
      self.accumulate_response({'status': 'OK', 'message': card_number})
      self.render_jresp()

# -------------------------

application = webapp2.WSGIApplication([
    ('/api/join_game', JoinGameHandler),
    ('/api/vote', VoteHandler),
    ('/api/cards', CardMappingHandler),
    ('/api/select_card', SelectCardHandler),
    ('/api/send_message', SendMessageHandler),
], debug=True)
