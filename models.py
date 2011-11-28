import random
import datetime
import logging

from google.appengine.api import channel
from ndb import model

import cards

GAME_STATES = ['new', 'start_round', 'voting', 'scores']
ROUNDS_PER_GAME = 5  # the count starts at 0

class Hangout(model.Model):
  current_game = model.KeyProperty()
  
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
        game.put()
        # aju added
        hangout.current_game = game.key
        dirty = True
      if dirty:
        model.put_multi([hangout, game])
      return game
    return model.transaction(_tx)


  @classmethod
  def start_new_game(cls, hangout_id):
    """If there is a current game, set its end time.  Then create a new game 
    as the current hangout game, using the participant list of the current game.
    Returns the new game.
    """
    # perform in txn: set the end date of the current
    # game and get its list of participant's plus ids.  Create the new game and
    # its new particpant objects from the list of plus ids. 
    def _tx():
      
      hangout = cls.get_by_id(hangout_id)
      if not hangout:  # TODO - should this be an error instead?
        hangout = cls(id=hangout_id)
      if hangout.current_game:
        current_game = hangout.current_game.get()
        current_game.end_time = datetime.datetime.now()
        # get the current active participants
        # TODO - do we need to set these to inactive?  don't think so,
        # since parent game will no longer be current.
        old_participants = current_game.participants()
        # old_participants = models.Participant.query(
        #     models.Participant.playing == True,
        #     ancestor=current_game.key).fetch()
      new_game = Game.new_game(hangout)
      new_game.put() # save now to generate key
      # associate new participant objects with new game
      # todo - factor out this common functionality from the 
      # Participant class method below
      new_participants = []
      for p in old_participants:
        newp = Participant(id=p.plus_id, parent=new_game.key)
        newp.channel_id = str(newp.key)
        # need to keep the same channel token (unless push out the new one somehow)
        newp.channel_token = p.channel_token
        newp.playing = True
        new_participants.append(newp)
      hangout.current_game = new_game.key
      model.put_multi(new_participants)
      model.put_multi([hangout, current_game])
      return new_game
    return model.transaction(_tx)
    pass


class Game(model.Model):
  # Child entity of the hangout this game is in

  state = model.StringProperty(choices=GAME_STATES, default='new')
  question_deck = model.IntegerProperty(repeated=True)
  answer_deck = model.IntegerProperty(repeated=True)
  current_question = model.IntegerProperty()
  is_paused = model.BooleanProperty(default=False)
  timeout_at = model.DateTimeProperty()
  start_time = model.DateTimeProperty(auto_now_add=True)
  end_time = model.DateTimeProperty()
  current_round = model.IntegerProperty()

  @classmethod
  def new_game(cls, hangout):
    question_deck = range(len(cards.questions))
    random.shuffle(question_deck)
    logging.info("question deck: %s", question_deck)
    answer_deck = range(len(cards.answers))
    random.shuffle(answer_deck)
    logging.info("answer_deck: %s", answer_deck)
    return cls(
        parent=hangout.key,
        state='new',
        current_round = 0,
        question_deck=question_deck,
        answer_deck=answer_deck
    )

  def participants(self):
    return Participant.query(
        Participant.playing == True,
        ancestor=self.key).fetch()

  def start_new_round(self):
    def _tx():
      self.state = 'start_round'
      random.shuffle(self.question_deck)
      random.shuffle(self.answer_deck)
      self.current_round += 1
      # now reset the participants' votes to None.
      participants = self.participants()
      for p in participants:
        p.vote = None
      self.put()
      model.put_multi(participants)
    model.transaction(_tx)

class Participant(model.Model):
  # Child entity of the Game in which they are participating
  
  channel_id = model.StringProperty(indexed=False)
  channel_token = model.StringProperty(indexed=False)
  playing = model.BooleanProperty(default=True)
  score = model.IntegerProperty(default=0)
  cards = model.IntegerProperty(repeated=True)
  selected_card = model.IntegerProperty()
  vote = model.KeyProperty()

  @property
  def plus_id(self):
    """The user's Google+ ID."""
    return self.key.id()

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
