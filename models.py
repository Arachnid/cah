import random
import datetime
import logging

from google.appengine.api import channel
from ndb import model

import cards

GAME_STATES = ['new', 'start_round', 'voting', 'scores']
ROUNDS_PER_GAME = 5  # the count starts at 0
SIZE_OF_HAND = 5  # the number of cards dealt to each participant per game


class Hangout(model.Model):
  """ Encodes information about a hangout and its child games, one of which
  is the current game.
  """

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
        hangout.current_game = game.key
        dirty = True
      if dirty:
        model.put_multi([hangout, game])
      return game
    return model.transaction(_tx)

  @classmethod
  def start_new_game(cls, hangout_id, old_participants):
    """If there is a current game, set its end time.  Then create a new game
    and set it as the current hangout game, using the participant list of the
    previous game. Returns the new game.
    """
    hangout = cls.get_by_id(hangout_id)
    if not hangout:  # TODO: should this be an error instead?
      hangout = cls(id=hangout_id)
    if hangout.current_game:
      current_game = hangout.current_game.get()
      current_game.end_time = datetime.datetime.now()
      # get the current active participants
      # TODO: do we need to set these to inactive?  don't think so,
      # since parent game will no longer be current, and we retrieve by parent
      # game.
      # old_participants = current_game.participants()
    new_game = Game.new_game(hangout)
    new_game.put() # save now to generate key
    # associate new participant objects, using plus_id of the old obj,
    # with the new game.
    new_participants = []
    for p in old_participants:
      newp = Participant(id=p.plus_id, parent=new_game.key)
      # keep the same channel id and token.
      # TODO - are there any issues in doing this?
      # (channel id is based on participant key from original game, but thus
      # far we don't ever need to reconstruct the keys).
      newp.channel_id = p.channel_id
      newp.channel_token = p.channel_token
      newp.hangout_score = p.hangout_score
      newp.playing = True
      new_participants.append(newp)
    new_game.select_new_question()
    # deal cards to the (copied-over) participants
    new_game.deal_hands(new_participants)
    hangout.current_game = new_game.key
    model.put_multi(new_participants)
    model.put_multi([hangout, current_game, new_game])
    return new_game


class Game(model.Model):
  """ Encode information about a hangout game.  Participants are child entities
  of a game.
  """

  state = model.StringProperty(choices=GAME_STATES, default='new')
  question_deck = model.IntegerProperty(repeated=True)
  answer_deck = model.IntegerProperty(repeated=True)
  current_question = model.IntegerProperty()
  # pause/timeout logic not yet implemented.
  is_paused = model.BooleanProperty(default=False)
  timeout_at = model.DateTimeProperty()
  start_time = model.DateTimeProperty(auto_now_add=True)
  end_time = model.DateTimeProperty()
  current_round = model.IntegerProperty()

  @classmethod
  def new_game(cls, hangout):
    """ Create a new game. This includes setting up a new shuffled question and
    answer deck.  The answer cards are 'dealt' as participant hands when the
    participants join.
    """
    question_deck = range(len(cards.questions))
    random.shuffle(question_deck)
    logging.info("question deck: %s", question_deck)
    answer_deck = range(len(cards.answers))
    random.shuffle(answer_deck)
    logging.info("answer_deck: %s", answer_deck)
    return cls(
        parent=hangout.key,
        state='new',
        current_round=0,
        question_deck=question_deck,
        answer_deck=answer_deck
    )

  def participants(self):
    return Participant.query(
        Participant.playing == True,
        ancestor=self.key).fetch()

  def message_all_participants(self, message):
    logging.info("in message_all_participants with msg: %s", message)
    for participant in self.participants():
      logging.info("sending channel msg to %s", participant.plus_id)
      channel.send_message(participant.channel_id, message)

  # TODO: for now, are basically assuming that we have enough answer cards
  # for all participants to get SIZE_OF_HAND of them.  Currently, if this is
  # not true, the latter participants just don't get cards.
  def deal_hands(self, participants):
    for p in participants:
      self.deal_hand(p)

  def deal_hand(self, participant):
    """ Deal a (randomly selected) hand from the game's answer deck.
    """
    deck_size = len(self.answer_deck)
    if deck_size < SIZE_OF_HAND:
      logging.warn("not enough cards")
      return None
    # this case, where the participant already has a hand dealt, 'should' not
    # actually come up.  (should it be an error if it does?)
    if participant.cards:
      return participant.cards
    participant.cards = []
    for _ in range(0, SIZE_OF_HAND):
      # note: since the deck is already shuffled, probably don't really need to
      # select randomly from it...
      idx = random.randint(0, deck_size-1)
      card = self.answer_deck[idx]
      participant.cards.append(card)
      del self.answer_deck[idx]
      deck_size -= 1
    model.put_multi([participant, self])
    logging.debug(
        "participant %s got hand %s", participant.plus_id, participant.cards)
    logging.debug("answer deck is now: %s", self.answer_deck)
    return participant.cards

  def select_new_question(self):
    """ select a question card (randomly) from the game's question deck.
    """
    logging.debug(
        "in select_new_question with starting qdeck: %s", self.question_deck)
    # select at random from the question deck (the random selection may be
    # overkill since deck is shuffled)
    qnum = random.randint(0, len(self.question_deck)-1)
    self.current_question = self.question_deck[qnum]
    # remove selected from the deck
    del self.question_deck[qnum]
    logging.info(
        "current question %s and new deck %s",
        self.current_question, self.question_deck)
    self.put()

  def start_new_round(self, participants):
    """ start a new round of the given game.
    """
    # first check that we have not maxed out the number of rounds for this
    # game.
    # The calling method 'should' have checked this already.
    if self.current_round >= ROUNDS_PER_GAME:
      # TODO - assuming it makes sense to have this be an exception, should
      # define a 'GameException' subclass or similar.
      raise Exception("Have reached last round in game; can't start new one.")
    self.state = 'start_round'
    # select a new question card for the round
    self.select_new_question()
    self.current_round += 1
    # now reset the participants' votes, card selections, and round score.
    # Keep the game and hangout scores.
    logging.info("in start_new_round, with participants %s", participants)
    for p in participants:
      p.vote = None
      p.selected_card = None
      p.score = 0
    self.put()
    model.put_multi(participants)


class Participant(model.Model):
  """ Child entity of the Game in which it is participating."""
  
  channel_id = model.StringProperty(indexed=False)
  channel_token = model.StringProperty(indexed=False)
  playing = model.BooleanProperty(default=True)
  score = model.IntegerProperty(default=0) #score for round
  game_score = model.IntegerProperty(default=0) #score for game; not preserved
      # across games.
  # TODO - hangout_score is simply accumulated for the whole hangout,
  # not taking into account leave/join events.  Might want different logic.
  hangout_score = model.IntegerProperty(default=0)
  cards = model.IntegerProperty(repeated=True)
  selected_card = model.IntegerProperty()
  vote = model.KeyProperty()

  @property
  def plus_id(self):
    """The user's Google+ ID."""
    return self.key.id()

  @classmethod
  def get_or_create_participant(cls, game_key, plus_id):
    """ Either return the participant associated with the given plus_is,
    or create a new participant with that id, and deal them some cards.
    """

    def _tx():
      game = game_key.get()
      participant = cls.get_by_id(plus_id, parent=game_key)
      if not participant:
        participant = cls(id=plus_id, parent=game_key)
        participant.channel_id = str(participant.key)
        participant.channel_token = channel.create_channel(
            participant.channel_id)
      participant.playing = True
      # deal the hand for the participant.
      # TODO - deal with the case where the player did not get any cards,
      # indicated if hand is None.
      hand = game.deal_hand(participant)
      # if not hand:
        # react usefully if there were not enough cards for their hand.
      model.put_multi([participant, game])
      return participant
    return model.transaction(_tx)

  def select_card(self, card_num):
    """ select a card from the participant's hand.
    """
    if self.selected_card:  # if card already selected
      logging.warn(
          "Participant %s has already selected card %s",
          self.plus_id, self.selected_card)
      return False
    if card_num in self.cards:
      self.cards.remove(card_num)
      self.selected_card = card_num
      return card_num
    else:
      logging.warn(
          "selected card %s was not in participant's cards %s, %s",
          card_num, self.cards, self.plus_id)
      return None




