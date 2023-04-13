import json
import os
import requests
import time
import datetime

from pymongo import MongoClient


def load(filename):
    with open(filename, 'r') as file:
        return json.load(file)


class Domains:
    def __init__(self):
        self.page = 1
        self.page_count = 1

    def __iter__(self):
        return self

    def __next__(self):
        if self.page > self.page_count:
            raise StopIteration
        url = f'https://d3.ru/api/domains/?page={self.page}'
        response = requests.get(url).json()
        if response is None or 'status' in response and response['status'] == 'error':
            raise StopIteration
        self.page_count = response['page_count']
        self.page = response['page'] + 1
        domains = response['domains']
        if len(domains) > 0:
            return domains
        else:
            raise StopIteration


def save_domains():
    # сохранить сообщества в базу данных
    epoch = time.time()
    print('save domains')

    client = MongoClient(os.environ['MONGO'])
    db = client['dirty']
    domains_collection = db['domains']

    for domains in Domains():
        for domain in domains:
            try:
                _id = {
                    'prefix': domain['prefix'],
                    'epoch': time.time(),
                    'id': domain['id']
                }

                previous = domains_collection.find_one({
                    '_id.prefix': domain['prefix'],
                    '_id.id': domain['id']
                }, sort=[('_id.epoch', -1)])

                readers_count_change = 0

                domain_owner = ''

                try:
                    domain_owner = domain['owner']['login']
                except Exception as e:
                    print('domain_owner', e)

                if previous == None:
                    readers_count_change = 0
                    epoch_change = 0
                else:
                    readers_count_change = domain['readers_count'] - \
                        previous['readers_count']
                    epoch_change = _id['epoch'] - previous['_id']['epoch']

                    threshold = 10

                    if epoch_change < 60 * 60 * 24 * 7:
                        threshold = 5
                    elif epoch_change < 60 * 60 * 24:
                        threshold = 1

                    if domain_owner == 'r10o':
                        threshold = 1

                    if abs(readers_count_change) < threshold:
                        if abs(readers_count_change) >= threshold * 0.75:
                            print(
                                f'[-] {domain["prefix"]}\treaders: {domain["readers_count"]}\tchange: {readers_count_change}\tmust be: {threshold}')
                        continue

                doc = {
                    '_id': _id,
                    'readers_count': domain['readers_count'],
                    'readers_count_change': readers_count_change,
                    'epoch_change': epoch_change,
                    'owner': domain_owner,
                }

                print(
                    f'[+] {doc["_id"]["prefix"]}\treaders: {doc["readers_count"]}\tchange: {doc["readers_count_change"]}')

                domains_collection.replace_one({'_id': _id}, doc, upsert=True)
            except Exception as e:
                print('domain', domain, e)

    print(f'save domains done in {(time.time() - epoch) / 60} minutes')


def cache_domains():
    # кэш отчета по подписчикам сообществ
    client = MongoClient(os.environ['MONGO'])
    db = client['dirty']
    domains_collection = db['domains']
    cache_collection = db['cache']

    now = time.time()
    print('cache domains')

    prefixes = set()
    result = []

    for domain in domains_collection \
        .find({'_id.epoch': {'$gt': now - 7 * 60 * 60 * 24}, 'readers_count_change': {'$ne': 0}}) \
            .sort('_id.epoch', 1):

        if domain['_id']['prefix'] in prefixes:
            continue

        domain_info = requests.get(
            f'https://d3.ru/api/domains/{domain["_id"]["prefix"]}').json()
        if 'readers_count' not in domain_info:
            continue
        new_readers_count = domain_info['readers_count']
        old_readers_count = domain['readers_count'] - \
            domain['readers_count_change']
        readers_count_change = domain_info['readers_count'] - old_readers_count

        if new_readers_count == 0:
            continue

        result.append({
            'prefix': domain['_id']['prefix'],
            'old_readers_count': old_readers_count,
            'new_readers_count': new_readers_count,
            'readers_count_change': readers_count_change,
            'epoch_from': domain['_id']['epoch'] - domain['epoch_change'],
            'epoch_to': domain['_id']['epoch'],
            'epoch_change': domain['epoch_change'],
            'owner': domain_info['owner']['login'],
        })

        prefixes.add(domain['_id']['prefix'])

    doc = {
        '_id': 'domain_readers_change',
        'result': result
    }

    cache_collection.replace_one(
        {'_id': 'domain_readers_change'}, doc, upsert=True)

    print(f'cache domains done in {(time.time() - now) / 60} minutes')
    print(f'{len(result)} domains')


def save_posts():
    # сохранить посты в базу данных
    print('saving the posts')
    client = MongoClient(os.environ['MONGO'])
    db = client['dirty']
    posts_collection = db['posts']
    response = requests.get('https://d3.ru/api/posts').json()
    for post in response['posts']:
        try:
            post_response = requests.get(
                f'https://d3.ru/api/posts/{post["id"]}').json()
            print(f'https://d3.ru/{post["id"]}: "{post["title"]}", {post["domain"]["prefix"]}, {post["user"]["login"]}')
            views_count = post_response['views_count']

            now = time.time()
            doc = posts_collection.find_one({'_id': post['id']})
            if doc is None:
                doc = {
                    '_id': post['id'],
                    'title': post['title'],
                    'domain': post['domain']['prefix'],
                    'golden': post['golden'],
                    'rating': post['rating'],
                    'user': post['user']['login'],
                    'created': post['created'],
                    'comments_count': post['comments_count'],
                    'views_count': views_count,
                    'first_seen': now,
                    'last_seen': now,
                    'minutes': 10,
                    'checkpoints': [now]
                }
                posts_collection.insert_one(doc)
            else:
                checkpoints = doc['checkpoints']
                checkpoints.append(now)

                doc['title'] = post['title']
                doc['domain'] = post['domain']['prefix']
                doc['golden'] = post['golden']
                doc['rating'] = post['rating']
                doc['comments_count'] = post['comments_count']
                doc['views_count'] = views_count
                doc['last_seen'] = now
                doc['minutes'] += 10
                doc['checkpoints'] = checkpoints
                posts_collection.save(doc)
        except Exception as e:
            print(e)
    print('saving the posts done')


def test():
    print(f'test: {datetime.datetime.now()}')
