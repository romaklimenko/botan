import datetime
import json
import os
import random
import re
import requests
import time

from operator import itemgetter, attrgetter, methodcaller
from pymongo import MongoClient, ASCENDING, DESCENDING

headers = {
  'X-Futuware-UID': os.environ['BOTAN_UID'],
  'X-Futuware-SID': os.environ['BOTAN_SID'],
  'Content-Type': 'application/json'
}

headers_no_json = {
  'X-Futuware-UID': os.environ['BOTAN_UID'],
  'X-Futuware-SID': os.environ['BOTAN_SID']
}

def load(filename):
  with open(filename, 'r') as file:
    return json.load(file)

def get_answer(body):
  answers = load('botan.json')
  if ' бот.' in body:
    return random.choice(answers['bot'])
  if ' бот?' in body:
    return random.choice(answers['bot'])
  if ' бот,' in body:
    return random.choice(answers['bot'])
  if ' бот ' in body:
    return random.choice(answers['bot'])
  if 'Ром' in body:
    return random.choice(answers['roma'])
  if 'romaklimenko' in body:
    return random.choice(answers['roma'])
  if 'пасиб' in body:
    return random.choice(answers['thank'])
  if '?' in body:
    return random.choice(answers['question'])
  return random.choice(answers['default'])

# получить все новые упоминания
def get_all_new():
  url = 'https://d3.ru/api/my/notifications/unread/'
  notifications = requests.get(url, headers=headers).json()['notifications']
  return list(
    filter(lambda n: n['type'] == 'mention' or n['type'] == 'comment_answer',
    notifications))

# отметить все уведомления как прочитанные
def mark_all_as_read():
  url = 'https://d3.ru/api/my/notifications/mark_read/'
  requests.post(url, headers=headers)

# ответить на комментарий
def reply_to_comment(domain, post_id, comment_id, parent_body, user):
  body = f'{user}, {get_answer(parent_body)}'
  print(f'{user}: {parent_body}')
  print(f'answer: {body}')
  url = f'https://{domain}.d3.ru/api/posts/{post_id}/comments/'
  response = requests.post(
    url,
    data={ 'parent_comment_id': comment_id, 'body': body },
    headers=headers_no_json)
  print(response)

# ответить всем
def reply_all():
  print('reply_all')
  notifications = get_all_new()

  for notification in notifications:
    post_id = notification['data']['post']['id']
    if 'comment' not in notification['data']:
      continue
    comment_id = notification['data']['comment']['id']
    domain = notification['data']['comment']['domain']['prefix']
    user = notification['data']['comment']['user']['login']
    body = notification['data']['comment']['body']
    if domain not in ['dataisbeautiful', 'etymology', 'denmark', 'romaklimenko', 'reports', 'unsplash', 'adm', 'lyrics', 'notes'] and user != 'romaklimenko':
      continue
    print(f'post_id: {post_id}, comment_id: {comment_id}, user: {user}, domain: {domain}')
    print('\n')
    reply_to_comment(domain, post_id, comment_id, body, user)
    time.sleep(5)
    # break

  mark_all_as_read()

# enumerator для сообществ, очень удобно
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

# сохранить сообщества в базу данных
def save_domains():
  epoch = time.time()
  print('save domains')

  client = MongoClient(os.environ['MONGO'])
  db = client['dirty']
  domains_collection = db['domains']

  for domains in Domains():
    for domain in domains:
      try:
        # if domain['readers_count'] < 100:
        #   continue

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

        if previous == None:
          readers_count_change = 0
          epoch_change = 0
        else:
          readers_count_change = domain['readers_count'] - previous['readers_count']
          epoch_change = _id['epoch'] - previous['_id']['epoch']

          threshold = 10

          if epoch_change < 60 * 60 * 24 * 7:
            threshold = 5
          elif epoch_change < 60 * 60 * 24:
            threshold = 1

          try: # smells bad, but it's ok
            if domain['owner']['login'] == 'r10o':
              threshold = 1
          except Exception as e:
            print('domain owner', e)

          if abs(readers_count_change) < threshold:
            if abs(readers_count_change) >= threshold * 0.75:
              print(f'[-] {domain["prefix"]}\treaders: {domain["readers_count"]}\tchange: {readers_count_change}\tmust be: {threshold}')
            continue

        doc = {
          '_id': _id,
          'readers_count': domain['readers_count'],
          'readers_count_change': readers_count_change,
          'epoch_change': epoch_change
        }

        print(f'[+] {doc["_id"]["prefix"]}\treaders: {doc["readers_count"]}\tchange: {doc["readers_count_change"]}')

        domains_collection.replace_one({ '_id': _id }, doc, upsert=True)
      except Exception as e:
        print(e)

  print(f'save domains done in {(time.time() - epoch) / 60} minutes')

# кэш отчета по подписчикам сообществ
def cache_domains():
  client = MongoClient(os.environ['MONGO'])
  db = client['dirty']
  domains_collection = db['domains']
  cache_collection = db['cache']

  now = time.time()
  print('cache domains')

  prefixes = set()
  result = []

  for domain in domains_collection \
    .find({ '_id.epoch': { '$gt': now - 7 * 60 * 60 * 24 }, 'readers_count_change': { '$ne': 0 } }) \
    .sort('_id.epoch', 1):

    if domain['_id']['prefix'] in prefixes:
      continue

    domain_info = requests.get(f'https://d3.ru/api/domains/{domain["_id"]["prefix"]}').json()
    new_readers_count = domain_info['readers_count']
    old_readers_count = domain['readers_count'] - domain['readers_count_change']
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
    })

    prefixes.add(domain['_id']['prefix'])

  doc = {
    '_id': 'domain_readers_change',
    'result': result
  }

  cache_collection.replace_one({ '_id': 'domain_readers_change' }, doc, upsert=True)

  print(f'cache domains done in {(time.time() - now) / 60} minutes')
  print(f'{len(result)} domains')

# сохранить посты в базу данных
def save_posts():
  print('saving the posts')
  client = MongoClient(os.environ['MONGO'])
  db = client['dirty']
  posts_collection = db['posts']
  response = requests.get('https://d3.ru/api/posts').json()
  for post in response['posts']:
    try:
      post_response = requests.get(f'https://d3.ru/api/posts/{post["id"]}').json()
      # print(f'https://d3.ru/{post["id"]}/')
      views_count = post_response['views_count']

      now = time.time()
      doc = posts_collection.find_one({ '_id': post['id'] })
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
          'checkpoints': [ now ]
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

# старый метод, сохранявший посты для отчетов на reports
def save_posts_old():
  client = MongoClient(os.environ['MONGO'])
  db = client['dirty']
  posts_collection = db['responses']
  response = requests.get('https://d3.ru/api/posts').json()
  for post in response['posts']:
    if 'data' in post:
      post.pop('data')
  created = time.time()
  doc = {
    '_id': created,
    'response': response
  }
  posts_collection.insert_one(doc)
  posts_collection.delete_many({ '_id': { '$lt': created - 60 * 60 * 24 * 30 } })

# запостить отчет о подписчиках на reports
def post_domains_stats(epoch_from, epoch_to, domain_prefix='staging'):
  checkpoints = get_checkpoints(epoch_from, epoch_to)
  diff = compare_checkpoints(checkpoints['checkpoint_a'], checkpoints['checkpoint_b'])

  date_from = checkpoints['checkpoint_a']['_id']
  date_from = f'{date_from[8:10]}.{date_from[5:7]}.{date_from[:4]}'
  date_to = checkpoints['checkpoint_b']['_id']
  date_to = f'{date_to[8:10]}.{date_to[5:7]}.{date_to[:4]}'

  post_data = dict()
  post_data['title'] = f'Сообщества с {date_from} по {date_to}'
  post_data['increasing'] = list()
  post_data['decreasing'] = list()
  domains = list()
  for id in diff:
    domains.append(diff[id])
  post_data['decreasing'] = list(filter(lambda x: x['diff'] < -1, domains))#[:10]
  post_data['decreasing'].sort(key=lambda x: (x['diff'], -x['readers_count_a']))
  post_data['increasing'] = list(filter(lambda x: x['diff'] > 1, domains))#[:10]
  post_data['increasing'].sort(key=lambda x: (x['diff'], x['readers_count_a']), reverse=True)

  post_text = f'За период с {date_from} по {date_to} в сообществах произошли следующие изменения:\n\n'
  if len(post_data['increasing']) > 0:
    post_text += '<b>Сообщества, которые набрали больше одного подписчика:</b>\n'
    for domain in post_data['increasing']:
      post_text += f'- <a href="{domain["url"]}">{domain["prefix"]}</a> было {domain["readers_count_a"]}, стало {domain["readers_count_b"]}, прирост {domain["diff"]}\n'

  post_text += '\n\n'

  if len(post_data['decreasing']) > 0:
    post_text += '<b>Сообщества, которые потеряли больше одного подписчика:</b>\n'
    for domain in post_data['decreasing']:
      post_text += f'- <a href="{domain["url"]}">{domain["prefix"]}</a> было {domain["readers_count_a"]}, стало {domain["readers_count_b"]}, убыль {domain["diff"]}\n'

  post_text += '\n\n'

  data = {
    'data': {
      'text': post_text,
      'type': 'link',
      'title': post_data['title']
    },
    'tags': [
      'сообщества',
      'подписчики'
    ]
  }

  draft = requests.post('https://d3.ru/api/drafts/', headers=headers, json=data).json()
  draft_id = draft['id']

  requests.post(f'https://d3.ru/api/drafts/{draft_id}/publish/?domain_prefix={domain_prefix}', headers=headers)

def get_warning(domain_prefix):
  coronavirus = load('coronavirus.json')
  politics = load('politics.json')
  if domain_prefix in coronavirus:
    return '🦠'
  elif domain_prefix in politics:
    return '⚠️'
  return '-'

# отчет о постах на главной для reports
def post_tops(domain_prefix='staging'):
  limit = 20
  now = time.time()

  client = MongoClient(os.environ['MONGO'])
  db = client['dirty']
  responses_collection = db['responses']

  posts_by_id = dict()

  posts_by_lifetime = dict()

  for response in responses_collection.find({ '_id': { '$gt': now - 60 * 60 * 24 * 10 } }):
    for post in response['response']['posts']:
      id = post['id']
      posts_by_id[id] = post
      if id in posts_by_lifetime:
        posts_by_lifetime[id] += 1
      else:
        posts_by_lifetime[id] = 1

  posts = dict()

  for response in responses_collection.find({ '_id': { '$gt': now - 60 * 60 * 24 * 7 } }):
    for post in response['response']['posts']:
      posts[post['id']] = post

  users_by_post_count = dict()
  domains_by_post_count = dict()

  for id in posts:
    user = posts[id]['user']['login']
    if user in users_by_post_count:
      users_by_post_count[user] += 1
    else:
      users_by_post_count[user] = 1

    domain = posts[id]['domain']['prefix']
    if domain in domains_by_post_count:
      domains_by_post_count[domain] += 1
    else:
      domains_by_post_count[domain] = 1

  posts_by_lifetime = dict(sorted(posts_by_lifetime.items(), key=itemgetter(1), reverse=True))
  users_by_post_count = dict(sorted(users_by_post_count.items(), key=itemgetter(1), reverse=True))
  domains_by_post_count = dict(sorted(domains_by_post_count.items(), key=itemgetter(1), reverse=True))

  post_text = '<b>Посты, дольше всего провисевшие на <a href="https://d3.ru/">главной</a> за последние десять дней:</b>\n'

  posts_bottom = 0
  non_political_count = 0
  skipped_political_count = 0
  for post_id in list(posts_by_lifetime):
    if posts_by_lifetime[post_id] < posts_bottom:
      break

    post = posts_by_id[post_id]

    if post['domain']['prefix'] in politics or post['domain']['prefix'] in coronavirus:
      skipped_political_count += 1
      continue
    non_political_count += 1
    if non_political_count > limit:
      posts_bottom = posts_by_lifetime[post_id]
    warining = get_warning(post["domain"]["prefix"])
    post_text += f'{warining} {post["domain"]["prefix"]}, автор @{post["user"]["login"]}, пост "<a href="{post["domain"]["url"]}/{post["id"]}">{post["title"]}</a>", {posts_by_lifetime[post_id]} ч.\n'

  post_text += f'<br>Чтобы составить этот список постов, нам пришлось удалить {skipped_political_count} постов ⚠️политизированных и 🦠коронавирусных сообществ. '
  post_text += f'Если бы мы этого не сделали, то топ постов d3 выглядел бы так:\n'

  post_text += '<br><b>Посты, дольше всего провисевшие на <a href="https://d3.ru/">главной</a> за последние десять дней:</b>\n'

  posts_bottom = posts_by_lifetime[list(posts_by_lifetime)[:limit][-1]]

  for post_id in list(posts_by_lifetime):
    if posts_by_lifetime[post_id] < posts_bottom:
      break
    post = posts_by_id[post_id]

    warning = get_warning(post['domain']['prefix'])
    post_text += f'{warning} {post["domain"]["prefix"]}, автор @{post["user"]["login"]}, пост "<a href="{post["domain"]["url"]}/{post["id"]}">{post["title"]}</a>", {posts_by_lifetime[post_id]} ч.\n'

  post_text += f'\n<i><sup>*</sup>Политические и политизированные сообщества отмечены символом ⚠️</i>'

  post_text += '<br><br><b>Сообщества, с наибольшим количеством постов, попавших на <a href="https://d3.ru/">главную</a> за последние семь дней:</b>\n'

  domains_bottom = domains_by_post_count[list(domains_by_post_count)[:limit][-1]]

  for prefix in list(domains_by_post_count):
    if domains_by_post_count[prefix] < domains_bottom:
      break
    warning = get_warning(prefix)
    post_text += f'{warning} <a href="https://{prefix}.d3.ru">{prefix}</a> – {domains_by_post_count[prefix]} постов\n'

  post_text += '<br><br><b>Пользователи, с наибольшим количеством постов, попавших на <a href="https://d3.ru/">главную</a> за последние семь дней:</b>\n'

  users_bottom = users_by_post_count[list(users_by_post_count)[:limit][-1]]

  for prefix in list(users_by_post_count):
    if users_by_post_count[prefix] < users_bottom:
      break
    post_text += f'- @{prefix} – {users_by_post_count[prefix]} постов\n'


  title = f'Главная и её обитатели по состоянию на {datetime.date.today().strftime("%d.%m.%Y")}'

  data = {
    'data': {
      'text': post_text,
      'type': 'link',
      'title': title
    },
    'tags': [
      'главная',
      'посты',
      'пользователи',
      'сообщества'
    ]
  }

  draft = requests.post('https://d3.ru/api/drafts/', headers=headers, json=data).json()
  draft_id = draft['id']

  requests.post(f'https://d3.ru/api/drafts/{draft_id}/publish/?domain_prefix={domain_prefix}', headers=headers)

# сравнивалка подписчиков. не помню как она работает, но она работает
def compare_checkpoints(checkpoint_a, checkpoint_b):
  domains = dict()
  domains_a = checkpoint_a['domains']
  max_domain_id = max(list(map(lambda x: domains_a[x]['id'], domains_a.keys())))
  for key_a in domains_a.keys():
    domain_a = domains_a[key_a]
    domains[key_a] = {
      'prefix': domain_a['prefix'],
      'readers_count_a': domain_a['readers_count'],
      'url': domain_a['url']
    }
  domains_b = checkpoint_b['domains']
  for key_b in domains_b.keys():
    domain_b = domains_b[key_b]
    if key_b in domains:
      domains[key_b]['readers_count_b'] = domain_b['readers_count']
      domains[key_b]['diff'] = domains[key_b]['readers_count_b'] - domains[key_b]['readers_count_a']
    else:
      diff = 0
      if domain_b['id'] > max_domain_id:
        diff = domain_b['readers_count']
      domains[key_b] = {
        'prefix': domain_b['prefix'],
        'readers_count_a': 0,
        'readers_count_b': domain_b['readers_count'],
        'diff': diff,
        'url': domain_b['url']
      }
  for key in domains.keys():
    if 'readers_count_b' not in domains[key]:
      domains[key]['readers_count_b'] = 0
      domains[key]['diff'] = 0

  return domains

# получить точки для сравнения подписчиков
def get_checkpoints(epoch_from, epoch_to):
  client = MongoClient(os.environ['MONGO'])
  db = client['dirty']
  domains_collection = db['domains']
  checkpoint_a = domains_collection.find_one({ '_id': str(datetime.date.fromtimestamp(epoch_from)) })
  checkpoint_b = domains_collection.find_one({ '_id': str(datetime.date.fromtimestamp(epoch_to)) })
  return {
    'checkpoint_a': checkpoint_a,
    'checkpoint_b': checkpoint_b
  }

# запостить черновик
def post_draft(domain_prefix='staging'):
  print('posting a draft')
  # get the first unread inbox that matches criteria
  inbox_id = None
  draft_id = None
  unread_inboxes = requests.get('https://d3.ru/api/inboxes/unread/', headers=headers) \
    .json()['inboxes']

  inboxes = list()
  for inbox in unread_inboxes:
    if inbox['user']['login'] != 'dirty':
      continue
    inboxes.append(inbox)

  inbox = random.choice(inboxes)

  sub_str = 'Пользователь <a href="//d3.ru/user/romaklimenko/" target="_top" class="c_user" data-user_id="36977">romaklimenko</a> передал вам черновик'
  text = inbox['data']['text']
  if sub_str in text:
    inbox_id = inbox['id']
    print(f'inbox_id{inbox_id}')
    m = re.search('<a href="//d3.ru/edit/(.+?)">тут</a>', text)
    if m:
      draft_id = int(m.group(1))
      print(f'draft_id: {draft_id}')
  if draft_id is None:
    print('didnt find the inbox')
    return
  requests.post(f'https://d3.ru/api/drafts/{draft_id}/publish/?domain_prefix={domain_prefix}', headers=headers)
  requests.post(f'https://d3.ru/api/inbox/{inbox_id}/view/', headers=headers)

# запостить случайный пост из коллекции в монге
def random_post():
  client = MongoClient(os.environ['MONGO'])
  db = client['dirty']
  drafts_collection = db['drafts']
  drafts = list(drafts_collection.find({'published': { '$exists': False }}))
  draft = random.choice(drafts)
  print(draft)
  draft_id = draft['_id']
  domain_prefix = draft['domain']
  print('domain', domain_prefix)
  print('id', draft_id)
  requests.post(f'https://d3.ru/api/drafts/{draft_id}/publish/?domain_prefix={domain_prefix}', headers=headers)
  drafts_collection.update_one({ '_id': draft_id }, { '$set': { 'published': 1 } })

def get_reddit_post(subreddit):
  url = f'https://www.reddit.com/r/{subreddit}/top/.json?t=week'
  posts = requests.get(url, headers = {'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 11_0_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36'}).json()

  client = MongoClient(os.environ['MONGO'])
  db = client['dirty']
  reddit_collection = db['reddit']

  for post in posts['data']['children']:
    if reddit_collection.find_one({ '_id': post['data']['id'] }) != None:
      print(f'Пост {post["data"]["id"]} уже был обработан. Пропускаем.')
      continue
    if 'url_overridden_by_dest' not in post['data'] or post['data']['url_overridden_by_dest'] == '':
      continue

    return post

def post_from_reddit(reddit_post, domain_prefix):
  if reddit_post == None:
    print(f'Не передан reddit-пост для публикации.')
    return
  reddit_post_id = reddit_post['data']['id']
  title = reddit_post['data']['title'][0:140]
  image_src = reddit_post['data']['url_overridden_by_dest']
  link = f'https://reddit.com{reddit_post["data"]["permalink"]}'
  body = f'{reddit_post["data"]["title"]}<br><a href="https://reddit.com{reddit_post["data"]["permalink"]}">Отсюда</a>.'

  print(reddit_post_id, title, link, image_src, domain_prefix)

  data = {
    'data': {
      'type': 'link',
      'title': title,
      'media': {
        'url': get_image_source(image_src)
      },
      'link': {
        'url': link
      },
      'text': body
    }
  }

  client = MongoClient(os.environ['MONGO'])
  db = client['dirty']
  reddit_collection = db['reddit']

  draft_response = requests.post('https://d3.ru/api/drafts/', headers=headers, json=data)
  if not draft_response.ok:
    print(draft_response)
    reddit_collection.insert_one({
      '_id': reddit_post_id,
      'status_code': draft_response.status_code,
      'text': draft_response.text
    })
    return
  draft = draft_response.json()
  draft_id = draft['id']

  response = requests.post(f'https://d3.ru/api/drafts/{draft_id}/publish/?domain_prefix={domain_prefix}', headers=headers)
  if not response.ok:
    print(response.text)
    reddit_collection.insert_one({
      '_id': reddit_post_id,
      'status_code': response.status_code,
      'text': response.text
    })
    return
  result = response.json()

  result['_id'] = reddit_post_id
  reddit_collection.insert_one(result)

  return result


def get_image_source(src):
  ajax_headers = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'Cookie': f'uid={os.environ["BOTAN_UID"]}; sid={os.environ["BOTAN_SID"]};'
  }

  data = {
    'url': src,
    'csrf_token': os.environ['BOTAN_CSRF']
  }

  response = requests.post('https://d3.ru/ajax/urls/info/', headers=ajax_headers, data=data).json()

  if response['status'] == 'OK':
    return response['stored_location']
  else:
    return None