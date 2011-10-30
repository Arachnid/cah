from google.appengine.api import channel
from ndb import model

class Game(model.Model):
  @property
  def hangout_id(self):
    return self.key().name()


class Participant(model.Model):
  # Child entity of the Game in which they are participating
  
  @property
  def plus_id(self):
    """The user's Google+ ID."""
    return self.key().name()

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

  channel_id = model.StringProperty(indexed=False)
  channel_token = model.StringProperty(indexed=False)
  playing = model.BooleanProperty(default=True)
