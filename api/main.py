# -*- coding: utf-8 -*-
import asyncio
import csv
import hashlib
import json
import logging
import os

import tornado.web

import api.base
import config
import update

logger = logging.getLogger(__name__)

EMOTICON_UPLOAD_PATH = os.path.join(config.DATA_PATH, 'emoticons')
EMOTICON_BASE_URL = '/emoticons'
CUSTOM_PUBLIC_PATH = os.path.join(config.DATA_PATH, 'custom_public')


class StaticHandler(tornado.web.StaticFileHandler):
    """为了使用Vue Router的history模式，把不存在的文件请求转发到index.html"""
    async def get(self, path, include_body=True):
        if path == '':
            await self._get_index(include_body)
            return

        try:
            await super().get(path, include_body)
        except tornado.web.HTTPError as e:
            if e.status_code != 404:
                raise
            # 不存在的文件请求转发到index.html，交给前端路由
            await self._get_index(include_body)

    async def _get_index(self, include_body=True):
        # index.html不缓存，防止更新后前端还是旧版
        self.set_header('Cache-Control', 'no-cache')
        await super().get('index.html', include_body)


class ServerInfoHandler(api.base.ApiHandler):
    async def get(self):
        cfg = config.get_config()
        self.write({
            'version': update.VERSION,
            'config': {
                'enableTranslate': cfg.enable_translate,
                'enableUploadFile': cfg.enable_upload_file,
                'loaderUrl': cfg.loader_url,
                'enableAdminPlugins': cfg.enable_admin_plugins,
            }
        })


class ServiceDiscoveryHandler(api.base.ApiHandler):
    async def get(self):
        cfg = config.get_config()
        self.write({
            'endpoints': cfg.registered_endpoints,
        })


class PingHandler(api.base.ApiHandler):
    async def get(self):
        self.set_status(204)


class UploadEmoticonHandler(api.base.ApiHandler):
    async def post(self):
        cfg = config.get_config()
        if not cfg.enable_upload_file:
            raise tornado.web.HTTPError(403)

        try:
            file = self.request.files['file'][0]
        except LookupError:
            raise tornado.web.MissingArgumentError('file')
        if len(file.body) > 1024 * 1024:
            raise tornado.web.HTTPError(413, 'file is too large, size=%d', len(file.body))
        if not file.content_type.lower().startswith('image/'):
            raise tornado.web.HTTPError(415)

        url = await asyncio.get_running_loop().run_in_executor(
            None, self._save_file, file.body, self.request.remote_ip
        )
        self.write({'url': url})

    @staticmethod
    def _save_file(body, client):
        md5 = hashlib.md5(body).hexdigest()
        filename = md5 + '.png'
        path = os.path.join(EMOTICON_UPLOAD_PATH, filename)
        logger.info('client=%s uploaded file, path=%s, size=%d', client, path, len(body))

        tmp_path = path + '.tmp'
        with open(tmp_path, 'wb') as f:
            f.write(body)
        os.replace(tmp_path, path)

        return f'{EMOTICON_BASE_URL}/{filename}'


class EmoticonListHandler(api.base.ApiHandler):
    async def get(self):
        emoticons_path = os.path.join(config.DATA_PATH, 'emoticons.csv')
        if not os.path.exists(emoticons_path):
            raise tornado.web.HTTPError(404)

        emoticons = []

        with open(emoticons_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                emoticons.append({
                    'keyword': row[0],
                    'url': f'{EMOTICON_BASE_URL}/{row[1]}'
                })

        self.write(json.dumps(emoticons))


class NoCacheStaticFileHandler(tornado.web.StaticFileHandler):
    def set_extra_headers(self, path):
        self.set_header('Cache-Control', 'no-cache')


ROUTES = [
    (r'/api/server_info', ServerInfoHandler),
    (r'/api/endpoints', ServiceDiscoveryHandler),
    (r'/api/ping', PingHandler),
    (r'/api/emoticon', UploadEmoticonHandler),
    (r'/api/emoticons', EmoticonListHandler),
]
# 通配的放在最后
LAST_ROUTES = [
    (rf'{EMOTICON_BASE_URL}/(.*)', tornado.web.StaticFileHandler, {'path': EMOTICON_UPLOAD_PATH}),
    # 这个目录不保证文件内容不会变，还是不用缓存了
    (r'/custom_public/(.*)', NoCacheStaticFileHandler, {'path': CUSTOM_PUBLIC_PATH}),
    (r'/(.*)', StaticHandler, {'path': config.WEB_ROOT}),
]
