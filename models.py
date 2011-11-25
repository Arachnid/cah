import random

from google.appengine.api import channel
from ndb import model

import cards

GAME_STATES = ['new', 'start_round', 'voting', 'scores']

class Hangout(model.Model):
  current_game = db.KeyProperty()
  
  @property
  def hangout_id(self):
    return self.key.name()

  @classmethod
  def get_current_game(cls, hangout_id):
    """Retrieves the current game, or creates one if none exists."""
    def _tx():
      dirty = False
      hangout = cls.get_by_id(hangout_id)
      if not hangout:
        hangout = cls(id=hangout_id)
        dirty = True
      if hangout.current_game:
        game = hangout.current_game.get()
      else:
        game = Game.new_game(hangout)
        dirty = True
      if dirty:
        model.put_multi([hangout, game])
      return game
    return model.transaction(_tx)


class Game(model.Model):
  # Child entity of the hangout this game is in

  state = model.StringProperty(choices=STATES, default='new')
  question_deck = model.IntegerProperty(repeated=True)
  answer_deck = model.IntegerProperty(repeated=True)
  current_question = model.IntegerProperty()
  is_paused = model.BooleanProperty(required=True, default=False)
  timeout_at = model.DateTimeProperty()
  start_time = model.DateTimeProperty(required=True, auto_now_add=True)
  end_time = model.DateTimeProperty()

  @classmethod
  def new_game(cls, hangout):
    return cls(
        parent=hangout,
        state='new',
        question_deck=random.shuffle(range(len(cards.questions))),
        answer_deck=random.shuffle(range(len(cards.answers))),
    )


class Participant(model.Model):
  # Child entity of the Game in which they are participating
  
  channel_id = model.StringProperty(indexed=False)
  channel_token = model.StringProperty(indexed=False)
  playing = model.BooleanProperty(required=True, default=True)
  score = model.IntegerProperty(required=True, default=0)
  cards = model.IntegerProperty(repeated=True)
  selected_card = model.IntegerProperty()
  vote = model.KeyProperty()

  @property
  def plus_id(self):
    """The user's Google+ ID."""
    return self.key.name()

  @classmethod
  def get_participant(cls, game_key, plus_id):
    if isinstance(game_key, Game):
      game_key = game_key.key
    def _tx():
      participant = cls.get_by_id(plus_id, parent=game_key)
      if not participant:
        participant = cls(id=plus_id, parent=game_key)
        participant.channel_id = str(participant.key) 
        participant.channel_token = channel.create_channel(
            participant.channel_id)
      participant.playing = True
      participant.put()
      return participant
    return model.transaction(_tx)
