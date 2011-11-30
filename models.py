import random
import datetime
import logging

from google.appengine.api import channel
from ndb import model

import cards

GAME_STATES = ['new', 'start_round', 'voting', 'scores']
ROUNDS_PER_GAME = 5  # the count starts at 0
SIZE_OF_HAND = 5 # the number of cards dealt to each participant per game


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
        hangout.current_game = game.key
        dirty = True
      if dirty:
        model.put_multi([hangout, game])
      return game
    return model.transaction(_tx)


  # note: doesn't wrap the actions in its own txn, but should be performed in
  # the context of a txn.
  @classmethod
  def start_new_game(cls, hangout_id):
    """If there is a current game, set its end time.  Then create a new game 
    as the current hangout game, using the participant list of the current game.
    Returns the new game.
    """
    # set the end date of the current
    # game and get its list of participant's plus ids.  Create the new game and
    # its new participant objects from the list of plus ids. 

    # def _tx():
      
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
    # associate new participant objects, using plus_id of the old obj,
    # with the new game.
    new_participants = []
    for p in old_participants:
      newp = Participant(id=p.plus_id, parent=new_game.key)
      # hmm, should keep the same channel id and token,
      # unless push out the new one somehow. This might be problematic 
      # (channel id is based on participant key from original game).
      newp.channel_id = p.channel_id
      newp.channel_token = p.channel_token
      newp.playing = True
      new_participants.append(newp)
    # model.put_multi(new_participants)
    new_game.select_new_question()
    # deal cards to the (copied-over) participants
    new_game.deal_hands(new_participants)
    hangout.current_game = new_game.key
    model.put_multi(new_participants)
    model.put_multi([hangout, current_game, new_game])
    return new_game

    # return model.transaction(_tx)
    


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

  # TODO: for now, assume that we have enough answer cards for all participants
  # to get SIZE_OF_HAND of them.  If we don't throttle the number of
  # participants so that this is guaranteed, then we need to reduce the number
  # of cards per hand.
  # should be performed in context of txn
  def deal_hands(self, participants):
    for p in participants:
      self.deal_hand(p)


  # the participant should not be already holding any cards. [Do we need to
  # check for and handle that case?]
  # should be performed in context of txn
  def deal_hand(self, participant):
    deck_size = len(self.answer_deck)
    if deck_size < SIZE_OF_HAND:
      logging.warn("not enough cards")
      return
    participant.cards = []
    for i in range(0,SIZE_OF_HAND):
      idx = random.randint(0, deck_size-1)
      card = self.answer_deck[idx]
      participant.cards.append(card)
      del(self.answer_deck[idx])
      deck_size -= 1
    model.put_multi([participant, self])
    logging.info(
        "participant %s got hand %s", participant.plus_id, participant.cards)
    logging.info("answer deck is now: %s", self.answer_deck)


  def select_new_question(self):
    logging.info(
        "in select_new_question with starting qdeck: %s", self.question_deck)
    # select at random from the question deck
    qnum = random.randint(0, len(self.question_deck)-1)
    self.current_question = self.question_deck[qnum]
    # remove selected from the deck
    del(self.question_deck[qnum])
    logging.info(
        "current question %s and new deck %s", 
        self.current_question, self.question_deck)
    self.put()

  
  # note: not in its own txn, but is called in the context of a txn.
  def start_new_round(self):
    self.state = 'start_round'
    # random.shuffle(self.question_deck)
    # random.shuffle(self.answer_deck)
    # select a new question card for the round
    self.select_new_question()
    self.current_round += 1
    # now reset the participants' votes and card selections to None.
    participants = self.participants()
    for p in participants:
      p.vote = None
      p.selected_card = None
    self.put()
    model.put_multi(participants)


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
  def get_or_create_participant(cls, game_key, plus_id):
    # require game key
    # if isinstance(game_key, Game):
      # game_key = game_key.key
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
      # TODO - check if enough cards etc. ?
      game.deal_hand(participant)
      model.put_multi([participant, game])
      return participant
    return model.transaction(_tx)


  # tbd.  Select a card from the participant's hand
  # card_num is the card number, not the card's index in the list.
  def select_card(self, card_num):
    if card_num in self.cards:
      self.cards.remove(card_num)
      self.selected_card = card_num
    else:
      logging.warn(
          "selected card %s was not in participant's cards %s, %s",
          card_num, self.cards, self.plus_id)




