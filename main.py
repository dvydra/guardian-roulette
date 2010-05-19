from django.utils import simplejson
from google.appengine.api import urlfetch
from google.appengine.api import users
from google.appengine.api.labs import taskqueue
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.api import memcache
import datetime
import logging
import random 
import time
import os
from google.appengine.ext.webapp import template
from dateutil import parser

API_URL = "http://content.guardianapis.com/search?from-date=%s&to-date=%s&format=json&page-size=50"

class GuardianPage(db.Model):
    url = db.StringProperty(required=True)
    web_publication_datetime = db.DateTimeProperty()
    section = db.StringProperty(required=True)
    model_version = db.IntegerProperty()

def generate_url(page):
    today = datetime.date.today().strftime("%Y-%m-%d")
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    TODAYS_URL = API_URL % (yesterday,today,)
    return TODAYS_URL+"&page=%d" % page

def get_pages(memcache_key, gql_query):
    pages = memcache.get(memcache_key)
    if pages is None:
        pages = db.GqlQuery(
            gql_query, 
            datetime.datetime.now() - datetime.timedelta(days=1),
        )
        if not memcache.add(memcache_key, pages, 1800):
            logging.error("Memcache set for %s failed." % memcache_key)
    return pages

class RandomHandler(webapp.RequestHandler):
    def head(self):
        self.response.clear()
        self.response.set_status(200)  
    def get(self):
        pages = get_pages(
            "all_pages",
            "SELECT * FROM GuardianPage WHERE web_publication_datetime > :1",
        )       
        if pages.count() == 0:
            return self.error(404)
        r = random.randint(0, pages.count()-1)
        template_values = {
            'url': pages[r].url,
        }
        path = os.path.join(os.path.dirname(__file__), 'random.html')
        self.response.out.write(template.render(path, template_values))
        
class RandomSectionHandler(webapp.RequestHandler):
    def get(self, section):
        pages = db.GqlQuery("SELECT * FROM GuardianPage WHERE web_publication_datetime > :1 and section = :2", 
            datetime.datetime.now() - datetime.timedelta(days=1),
            section,
        )
        if pages.count() == 0:
            return self.error(404)
        r = random.randint(0,pages.count()-1)
        template_values = {
            'url': pages[r].url,
            'section': section,
        }
        path = os.path.join(os.path.dirname(__file__), 'random.html')
        self.response.out.write(template.render(path, template_values))

class LoadHandler(webapp.RequestHandler):
    def get(self):
        json = urlfetch.fetch(generate_url(1)).content
        response = simplejson.loads(json)
        number_of_pages = response['response']['pages']
      
        for i in range(1,number_of_pages+1):
            taskqueue.add(url='/load-worker', params={'page': i})

class LoadWorkerHandler(webapp.RequestHandler):
    def post(self):
        page = int(self.request.get('page'))
        response = simplejson.loads(urlfetch.fetch(generate_url(page)).content)
        for content in response['response']['results']:
            self.save_page(content)

    def save_page(self, content):
        if 'sectionId' in content:
            section = content['sectionId']
        else:
            section = 'global'
        url = content['webUrl']
        page = db.GqlQuery("SELECT * FROM GuardianPage WHERE url = :1", url).get()
        the_date = parser.parse(content['webPublicationDate'])
        web_publication_datetime = the_date
        if not page:
            GuardianPage(
                url = url,
                web_publication_datetime = web_publication_datetime,
                section = section,
                model_version = 1,
            ).put()

def main():
    application = webapp.WSGIApplication([
        ('/', RandomHandler),
        ('/random/(.*)', RandomSectionHandler), 
        ('/load', LoadHandler),
        ('/load-worker', LoadWorkerHandler),
    ],
    debug=True)
    util.run_wsgi_app(application)

if __name__ == '__main__':
    main()