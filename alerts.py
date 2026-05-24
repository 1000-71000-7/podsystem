import requests
import schedule
import time
from datetime import datetime, timedelta
from app import app, db
from database import Site, Event, Alert, PageSpeedMetric


def check_metrics_and_alert():
    """Проверяет метрики и отправляет оповещения"""
    with app.app_context():
        for site in Site.query.all():
            # Проверяем просмотры за последний час
            hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent_views = Event.query.filter(
                Event.site_id == site.id,
                Event.timestamp >= hour_ago,
                Event.event_type == 'pageview'
            ).count()

            # Если просмотров нет, а сайт должен работать - оповещаем
            if recent_views == 0:
                send_telegram_alert(
                    f"⚠️ ВНИМАНИЕ! Сайт '{site.name}'\n"
                    f"За последний час не зафиксировано ни одного просмотра.\n"
                    f"Возможны проблемы с доступностью сайта."
                )

            # Проверяем производительность
            last_metric = PageSpeedMetric.query.filter_by(
                site_id=site.id
            ).order_by(PageSpeedMetric.timestamp.desc()).first()

            if last_metric and last_metric.lcp:
                if last_metric.lcp > 4.0:
                    send_telegram_alert(
                        f"⚠️ Медленная загрузка сайта '{site.name}'\n"
                        f"LCP = {last_metric.lcp:.2f}с (норма < 2.5с)\n"
                        f"Это влияет на доступность формы обращений"
                    )


def send_telegram_alert(message):
    """Отправляет сообщение в Telegram"""
    token = app.config.get('TELEGRAM_BOT_TOKEN')
    chat_id = app.config.get('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        print(f"Telegram не настроен. Сообщение: {message}")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }, timeout=5)
        print(f"Оповещение отправлено: {message[:50]}...")
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")


def run_scheduler():
    """Запускает планировщик задач"""
    # Каждые 15 минут проверяем метрики
    schedule.every(15).minutes.do(check_metrics_and_alert)
    # Раз в час собираем PageSpeed метрики
    schedule.every().hour.do(collect_all_pagespeed)
    # Раз в сутки агрегируем данные
    schedule.every().day.at("00:05").do(aggregate_daily_data)

    while True:
        schedule.run_pending()
        time.sleep(60)


def collect_all_pagespeed():
    """Собирает PageSpeed метрики для всех сайтов"""
    from app import collect_pagespeed_metrics
    from database import PageSpeedMetric

    with app.app_context():
        for site in Site.query.all():
            metrics = collect_pagespeed_metrics(site.url)
            for strategy, data in metrics.items():
                if data:
                    metric = PageSpeedMetric(
                        site_id=site.id,
                        strategy=strategy,
                        lcp=data.get('lcp'),
                        fid=data.get('fid'),
                        cls=data.get('cls'),
                        ttfb=data.get('ttfb'),
                        performance_score=data.get('performance_score')
                    )
                    db.session.add(metric)
            db.session.commit()


def aggregate_daily_data():
    """Агрегирует данные за день"""
    from app import aggregate_daily_data as agg
    with app.app_context():
        agg()