from apscheduler.schedulers.background import BlockingScheduler

from botan import reply_all, save_posts, save_domains, cache_domains, get_reddit_post, post_from_reddit

sched = BlockingScheduler()

# каждый час отвечать на упоминания в комментариях
@sched.scheduled_job('cron', minute=0)
def reply_all_hourly():
  reply_all()

# каждые десять минут сохранять посты
@sched.scheduled_job('cron', minute='*/10')
def save_posts_every_10_minutes():
  save_posts()

# каждый час сохранять подписчиков сообществ
@sched.scheduled_job('cron', minute=50)
def save_domains_hourly():
  save_domains()
  cache_domains()

# каждый час постить посты с реддита
# @sched.scheduled_job('cron', minute=0)
# def post_propagandaposters_daily():
#   reddit_post = get_reddit_post('anormaldayinrussia')
#   post_from_reddit(reddit_post, 'anormaldayinrussia')

sched.start()