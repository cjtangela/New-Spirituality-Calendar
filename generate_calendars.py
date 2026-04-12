from pathlib import Path
from datetime import date, datetime, timedelta
import csv, hashlib, re, os
import requests, yaml
from bs4 import BeautifulSoup
from lunardate import LunarDate

base = Path(__file__).parent
DOCS = base / 'docs'
CONFIG = base / 'config'
CALENDARS = {
    '六斋日（绿色）': ('liuzhairi','#34A853'),
    '十斋日（橘色）': ('shizhairi','#FB8C00'),
    '灵性（蓝色）': ('lingxing','#4285F4'),
    '断食日（黄色）': ('duanshiri','#FBC02D'),
}
DAY_NAMES = {1:'初一',2:'初二',3:'初三',4:'初四',5:'初五',6:'初六',7:'初七',8:'初八',9:'初九',10:'初十',11:'十一',12:'十二',13:'十三',14:'十四',15:'十五',16:'十六',17:'十七',18:'十八',19:'十九',20:'二十',21:'二十一',22:'二十二',23:'二十三',24:'二十四',25:'二十五',26:'二十六',27:'二十七',28:'二十八',29:'二十九',30:'三十'}
MONTH_NAMES = {1:'正月',2:'二月',3:'三月',4:'四月',5:'五月',6:'六月',7:'七月',8:'八月',9:'九月',10:'十月',11:'冬月',12:'腊月'}
TEN_ZHAI = {1,8,14,15,18,23,24,28,29,30}
LONG_FASTING_MONTHS = {1,5,9}

class E:
    def __init__(self, cal, start, end, summary, description=''):
        self.cal=cal; self.start=start; self.end=end; self.summary=summary; self.description=description

def daterange(a,b):
    d=a
    while d<=b:
        yield d
        d += timedelta(days=1)

def lunar_records(start_year,end_year):
    records=[]; month_last={}
    for d in daterange(date(start_year,1,1), date(end_year,12,31)):
        lunar=LunarDate.fromSolarDate(d.year,d.month,d.day)
        leap=int(getattr(lunar,'isLeapMonth',False))
        key=(lunar.year,lunar.month,leap)
        month_last[key]=max(month_last.get(key,0),lunar.day)
        records.append((d,lunar.year,lunar.month,lunar.day,leap))
    return records, month_last

def buddhist(start_year,end_year):
    records, month_last=lunar_records(start_year,end_year)
    out=[]; month_bounds={}
    for d,ly,lm,ld,leap in records:
        month_bounds.setdefault((ly,lm,leap),[]).append(d)
        last=month_last[(ly,lm,leap)]
        six={8,14,15,23,29,30} if last==30 else {8,14,15,23,28,29}
        if ld in six:
            out.append(E('六斋日（绿色）',d,d+timedelta(days=1),f'斋戒-{DAY_NAMES[ld]}'))
        if ld in TEN_ZHAI and ld not in six and ld <= last:
            out.append(E('十斋日（橘色）',d,d+timedelta(days=1),DAY_NAMES[ld]))
    for (ly,lm,leap), ds in month_bounds.items():
        if not leap and lm in LONG_FASTING_MONTHS:
            out.append(E('十斋日（橘色）',min(ds),max(ds)+timedelta(days=1),f'长斋月-{MONTH_NAMES[lm]}'))
    return out

def spiritual(start_year,end_year):
    records,_=lunar_records(start_year,end_year)
    out=[]; seen1=set(); seen15=set()
    for d,ly,lm,ld,leap in records:
        k=(ly,lm,leap)
        if ld==1 and k not in seen1:
            out.append(E('灵性（蓝色）',d,d+timedelta(days=1),'新月')); seen1.add(k)
        if ld==15 and k not in seen15:
            out.append(E('灵性（蓝色）',d,d+timedelta(days=1),'满月')); seen15.add(k)
    for y in range(start_year,end_year+1):
        for n in range(1,13):
            d=date(y,n,n)
            out.append(E('灵性（蓝色）',d,d+timedelta(days=1),'星门'))
    return out

def ekadashi(start_year,end_year):
    manual={}
    f=CONFIG/'ekadashi_manual.csv'
    if f.exists():
        with f.open('r',encoding='utf-8-sig') as fh:
            for row in csv.DictReader(fh):
                if row.get('date'):
                    d=datetime.strptime(row['date'],'%Y-%m-%d').date()
                    manual.setdefault(d.year,[]).append(d)
    month_map_full = {m:i for i,m in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'], start=1)}
    month_map_short = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
    out=[]
    for y in range(start_year,end_year+1):
        dates=sorted(set(manual.get(y,[])))
        if not dates:
            scraped=set()
            urls=[
                'https://harekrishnamandir.org/ekadasi',
                f'https://www.baps.org/Calendar/{y}/EkadashiNomPunam.aspx',
                f'https://www.drikpanchang.com/vrats/ekadashidates.html?year={y}'
            ]
            for url in urls:
                try:
                    r=requests.get(url,timeout=30,headers={'User-Agent':'Mozilla/5.0'})
                    text=BeautifulSoup(r.text,'html.parser').get_text('\n',strip=True)
                    for month_name, day, yyyy in re.findall(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(\d{4})', text):
                        if int(yyyy)==y:
                            scraped.add(date(y,month_map_full[month_name],int(day)))
                    for mon, day in re.findall(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s*:\s*.*?Ekadashi', text):
                        scraped.add(date(y,month_map_short[mon],int(day)))
                except Exception:
                    pass
            dates=sorted(scraped)
        for d in dates:
            out.append(E('断食日（黄色）',d,d+timedelta(days=1),'断食日'))
    return out

def load_overrides():
    p=CONFIG/'manual_overrides.yaml'
    if not p.exists():
        return {'add':{}, 'remove':{}}
    data=yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    return {'add': data.get('add',{}) or {}, 'remove': data.get('remove',{}) or {}}

def apply_overrides(events):
    cfg=load_overrides(); kept=[]
    for ev in events:
        rules=cfg['remove'].get(ev.cal,[])
        if any((not r.get('start') or ev.start.isoformat()==r['start']) and (not r.get('summary') or ev.summary==r['summary']) for r in rules):
            continue
        kept.append(ev)
    for cal, items in cfg['add'].items():
        for item in items:
            s=datetime.strptime(item['start'],'%Y-%m-%d').date()
            e=datetime.strptime(item.get('end',item['start']),'%Y-%m-%d').date()
            if e<=s: e=s+timedelta(days=1)
            kept.append(E(cal,s,e,item['summary'],item.get('description','')))
    return kept

def esc(s):
    return str(s).replace('\\','\\\\').replace(';','\\;').replace(',','\\,').replace('\n','\\n')

def uid(cal,start,summary):
    return hashlib.md5(f'{cal}|{start.isoformat()}|{summary}'.encode()).hexdigest() + '@spiritual-calendar'

def write_ics(calendar_name, events, path, color):
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Jitong Spiritual Calendar//CN','CALSCALE:GREGORIAN',f'X-WR-CALNAME:{esc(calendar_name)}',f'X-APPLE-CALENDAR-COLOR:{color}','X-WR-TIMEZONE:Asia/Shanghai']
    stamp=datetime.now().strftime('%Y%m%dT%H%M%SZ')
    for ev in sorted(events,key=lambda x:(x.start,x.summary)):
        lines += ['BEGIN:VEVENT',f'UID:{uid(ev.cal,ev.start,ev.summary)}',f'DTSTAMP:{stamp}',f'DTSTART;VALUE=DATE:{ev.start.strftime("%Y%m%d")}',f'DTEND;VALUE=DATE:{ev.end.strftime("%Y%m%d")}',f'SUMMARY:{esc(ev.summary)}']
        if ev.description:
            lines.append(f'DESCRIPTION:{esc(ev.description)}')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    path.write_text('\r\n'.join(lines)+'\r\n', encoding='utf-8')

def main():
    start_year=int(os.environ.get('START_YEAR','2026'))
    end_year=int(os.environ.get('END_YEAR','2030'))
    DOCS.mkdir(parents=True, exist_ok=True)
    events = buddhist(start_year,end_year) + spiritual(start_year,end_year) + ekadashi(start_year,end_year)
    events = apply_overrides(events)
    for cal, (slug, color) in CALENDARS.items():
        write_ics(cal, [e for e in events if e.cal==cal], DOCS/f'{slug}.ics', color)
    (DOCS/'index.html').write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>修行日历订阅</title><body><h1>修行日历订阅</h1><ul><li><a href='./liuzhairi.ics'>六斋日（绿色）</a></li><li><a href='./shizhairi.ics'>十斋日（橘色）</a></li><li><a href='./lingxing.ics'>灵性（蓝色）</a></li><li><a href='./duanshiri.ics'>断食日（黄色）</a></li></ul></body></html>", encoding='utf-8')

if __name__ == '__main__':
    main()
