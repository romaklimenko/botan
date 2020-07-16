from apscheduler.schedulers.background import BlockingScheduler

from botan import reply_all, save_posts, save_domains, cache_domains

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
def save_domains_daily():
  save_domains()
  cache_domains()

sched.start()