# coding: utf-8
from __future__ import print_function, unicode_literals

import os
import datetime
import json

from collections import OrderedDict, defaultdict

import tornado.escape
from icalendar import Calendar, Event

from bgmi import __version__
from bgmi.config import SAVE_PATH, DB_PATH, DANMAKU_API_URL
from bgmi.front.base import BaseHandler

from bgmi.models import Download, Bangumi, Followed, STATUS_NORMAL, STATUS_UPDATING, STATUS_END
from bgmi.utils import normalize_path


COVER_URL = '/bangumi/cover'  # website.cover_url
WEEK = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')


def make_dicts(cursor, row):
    return dict((cursor.description[idx][0], value)
                for idx, value in enumerate(row))


class BangumiHandler(BaseHandler):
    def get(self, _):
        if os.environ.get('DEV', False):
            with open(os.path.join(SAVE_PATH, _), 'rb') as f:
                self.write(f.read())
                self.finish()
        else:
            self.set_header('Content-Type', 'text/html')
            self.write('<h1>BGmi HTTP Service</h1>')
            self.write('<pre>Please modify your web server configure file\n'
                       'to server this path to \'%s\'.\n'
                       'e.g.\n\n'
                       '...\n'
                       'autoindex on;\n'
                       'location /bangumi {\n'
                       '    alias %s;\n'
                       '}\n'
                       '...\n</pre>' % (SAVE_PATH, SAVE_PATH)
                       )
            self.finish()


class BangumiPlayerHandler(BaseHandler):
    def get(self, bangumi_name):
        data = Followed(bangumi_name=bangumi_name)
        data.select_obj()

        bangumi_obj = Bangumi(name=bangumi_name)
        bangumi_obj.select_obj()

        if not data:
            for i in self.patch_list:
                if bangumi_name == i['bangumi_name']:
                    data = i
                    bangumi_obj.cover = i['cover']
                    break

        if not data:
            return self.write_error(404)

        episode_list = {}
        bangumi_path = os.path.join(SAVE_PATH, bangumi_name)
        for root, _, files in os.walk(bangumi_path):
            if not _ and files:
                _ = root.replace(bangumi_path, '').split(os.path.sep)
                base_path = root.replace(SAVE_PATH, '')
                if len(_) >= 2:
                    episode_path = root.replace(os.path.join(SAVE_PATH, bangumi_name), '')
                    if episode_path.split(os.path.sep)[1].isdigit():
                        episode = int(episode_path.split(os.path.sep)[1])
                    else:
                        continue
                else:
                    episode = -1

                for bangumi in files:
                    if bangumi.lower().endswith('.mp4'):
                        mp4_path = os.path.join(base_path, bangumi).replace(os.path.sep, '/')
                        mp4_path = os.path.join(os.path.dirname(mp4_path),
                                                tornado.escape.url_escape(os.path.basename(mp4_path)))
                        episode_list[episode] = {'path': mp4_path.replace(os.path.sep, '/')}
                        print(os.path.join(base_path, bangumi))
                        break

        if not episode_list:
            self.write('_(:3 There are nothing to play, please try again later.')
            self.finish()
        else:
            self.render('templates/dplayer.html', bangumi=episode_list, bangumi_name=bangumi_name,
                        bangumi_cover='{}/{}'.format(COVER_URL, normalize_path(bangumi_obj['cover'])),
                        DANMAKU_URL=DANMAKU_API_URL)


class ImageCSSHandler(BaseHandler):
    def get(self):
        data = Followed.get_all_followed(status=None, bangumi_status=None)
        data.extend(self.patch_list)
        for _ in data:
            _['cover'] = '{}/{}'.format(COVER_URL, normalize_path(_['cover']))

        self.set_header('Content-Type', 'text/css; charset=utf-8')
        self.render('templates/image.css', data=data)


class RssHandler(BaseHandler):
    def get(self):
        data = Download.get_all_downloads()
        self.set_header('Content-Type', 'text/xml')
        self.render('templates/download.xml', data=data)


class CalendarHandler(BaseHandler):
    def get(self):
        type_ = self.get_argument('type', 0)

        cal = Calendar()
        cal.add('prodid', '-//BGmi Followed Bangumi Calendar//bangumi.ricterz.me//')
        cal.add('version', '2.0')

        data = Followed.get_all_followed(order='followed.updated_time', desc=True)
        data.extend(self.patch_list)

        if type_ == 0:

            bangumi = defaultdict(list)
            [bangumi[Bangumi.week.index(i['update_time']) + 1].append(i['bangumi_name']) for i in data]

            weekday = datetime.datetime.now().weekday()
            for i, k in enumerate(range(weekday, weekday + 7)):
                if k % 7 in bangumi:
                    for v in bangumi[k % 7]:
                        event = Event()
                        event.add('summary', v)
                        event.add('dtstart', datetime.datetime.now().date() + datetime.timedelta(i - 1))
                        event.add('dtend', datetime.datetime.now().date() + datetime.timedelta(i - 1))
                        cal.add_component(event)
        else:
            data = [bangumi for bangumi in data if bangumi['status'] == 2]
            for bangumi in data:
                event = Event()
                event.add('summary', 'Updated: {}'.format(bangumi['bangumi_name']))
                event.add('dtstart', datetime.datetime.now().date())
                event.add('dtend', datetime.datetime.now().date())
                cal.add_component(event)

        cal.add('name', 'Bangumi Calendar')
        cal.add('X-WR-CALNAM', 'Bangumi Calendar')
        cal.add('description', 'Followed Bangumi Calendar')
        cal.add('X-WR-CALDESC', 'Followed Bangumi Calendar')

        self.write(cal.to_ical())
        self.finish()


class MainHandler(BaseHandler):
    def get(self):
        is_json = self.get_argument('json', False)
        is_old = self.get_argument('old', False)

        if not os.path.exists(DB_PATH):
            self.write('BGmi db file not found.')
            self.finish()
            return

        data = Followed.get_all_followed(STATUS_NORMAL, STATUS_UPDATING,
                                         order='followed.updated_time', desc=True)

        followed = list(map(lambda b: b['bangumi_name'], data))
        followed.extend(list(map(lambda b: b['bangumi_name'], self.patch_list)))

        data = Followed.get_all_followed(STATUS_NORMAL, STATUS_UPDATING if not is_old else STATUS_END,
                                         order='followed.updated_time', desc=True)

        data.extend(self.patch_list)
        data.sort(key=lambda _: _['updated_time'] if _['updated_time'] else 7258093261)  # 2200年,应该不会有比这个大的吧...
        data.reverse()

        calendar = Bangumi.get_all_bangumi()

        for i in self.patch_list:
            calendar[i['update_time'].lower()].append(i)

        def shift(seq, n):
            n %= len(seq)
            return seq[n:] + seq[:n]

        weekday_order = shift(WEEK, datetime.datetime.today().weekday())
        cal_ordered = OrderedDict()

        for week in weekday_order:
            cal_ordered[week] = calendar[week.lower()]

        if is_json:
            self.write(json.dumps(cal_ordered))
            self.finish()
        else:
            self.render('templates/bangumi.html', data=data, cal=cal_ordered,
                        followed=list(followed), version=__version__)