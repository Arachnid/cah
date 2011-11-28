# import uuid
import webapp2
from webapp2_extras import jinja2
# from ndb import model
# import logging


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
    self.response.write("%s(%s);" % (cb,
                                     simplejson.dumps(response)))
