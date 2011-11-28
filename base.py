import webapp2
from webapp2_extras import jinja2
# from ndb import model
import logging


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
    cb = self.request.GET.get('callback')
    if not cb:
      logging.warn("in render_jsonp, could not get callback URL.")
      self.error(500)
      return
    self.response.write("%s(%s);" % (cb,
                                     simplejson.dumps(response)))
