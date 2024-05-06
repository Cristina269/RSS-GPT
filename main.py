import feedparser
import configparser
import os
import httpx
from openai import OpenAI
from jinja2 import Template
from bs4 import BeautifulSoup
import re
import datetime
#from dateutil.parser import parse

def generate_untitled(entry):
    try: return entry.title
    except: 
        try: return entry.article[:50]
        except: return entry.link

def get_cfg(sec, name, default=None):
    value=config.get(sec, name, fallback=default)
    if value:
        return value.strip('"')

def clean_html(html_content):
    """
    This function is used to clean the HTML content.
    It will remove all the <script>, <style>, <img>, <a>, <video>, <audio>, <iframe>, <input> tags.
    Returns:
        Cleaned text for summarization
    """
    soup = BeautifulSoup(html_content, "html.parser")

    for script in soup.find_all("script"):
        script.decompose()

    for style in soup.find_all("style"):
        style.decompose()

    for img in soup.find_all("img"):
        img.decompose()

    for a in soup.find_all("a"):
        a.decompose()

    for video in soup.find_all("video"):
        video.decompose()

    for audio in soup.find_all("audio"):
        audio.decompose()
    
    for iframe in soup.find_all("iframe"):
        iframe.decompose()
    
    for input in soup.find_all("input"):
        input.decompose()

    return soup.get_text()

def filter_entry(entry, filter_apply, filter_type, filter_rule):
    """
    This function is used to filter the RSS feed.

    Args:
        entry: RSS feed entry
        filter_apply: title, article or link
        filter_type: include or exclude or regex match or regex not match
        filter_rule: regex rule or keyword rule, depends on the filter_type

    Raises:
        Exception: filter_apply not supported
        Exception: filter_type not supported
    """
    if filter_apply == 'title':
        text = entry.title
    elif filter_apply == 'article':
        text = entry.article
    elif filter_apply == 'link':
        text = entry.link
    elif not filter_apply:
        return True
    else:
        raise Exception('filter_apply not supported')

    if filter_type == 'include':
        return re.search(filter_rule, text)
    elif filter_type == 'exclude':
        return not re.search(filter_rule, text)
    elif filter_type == 'regex match':
        return re.search(filter_rule, text)
    elif filter_type == 'regex not match':
        return not re.search(filter_rule, text)
    elif not filter_type:
        return True
    else:
        raise Exception('filter_type not supported')

def read_entry_from_file(sec):
    """
    This function is used to read the RSS feed entries from the feed.xml file.

    Args:
        sec: section name in config.ini
    """
    out_dir = os.path.join(BASE, get_cfg(sec, 'name'))
    try:
        with open(out_dir + '.xml', 'r') as f:
            rss = f.read()
        feed = feedparser.parse(rss)
        return feed.entries
    except:
        return []

def truncate_entries(entries, max_entries):
    if len(entries) > max_entries:
        entries = entries[:max_entries]
    return entries

def gpt_summary(query,model,language):
    if language == "zh":
        messages = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": f"请用中文总结这篇文章，先提取出{keyword_length}个关键词，在同一行内输出，然后换行，用中文在{summary_length}字内写一个包含所有要点的总结，按顺序分要点输出，并按照以下格式输出'<br><br>总结:'，<br>是HTML的换行符，输出时必须保留2个，并且必须在'总结:'二字之前"}
        ]
    else:
        messages = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": f"Please summarize this article in {language} language, first extract {keyword_length} keywords, output in the same line, then line break, write a summary containing all the points in {summary_length} words in {language}, output in order by points, and output in the following format '<br><br>Summary:' , <br> is the line break of HTML, 2 must be retained when output, and must be before the word 'Summary:'"}
        ]
    if not OPENAI_PROXY:
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
        )
    else:
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            # Or use the `OPENAI_BASE_URL` env var
            base_url=OPENAI_BASE_URL,
            # example: "http://my.test.server.example.com:8083",
            http_client=httpx.Client(proxy=OPENAI_PROXY),
            # example:"http://my.test.proxy.example.com",
        )
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    return completion.choices[0].message.content

def output(sec, language):
    """Outputs summaries and links of RSS feed entries.

    Args:
        sec: section name in config.ini
        language: language code for summary generation

    Raises:
        Exception: If filter criteria are not properly set in config.ini
    """
    # Configuration and logging setup
    log_file = os.path.join(BASE, get_cfg(sec, 'name') + '.log')
    out_dir = os.path.join(BASE, get_cfg(sec, 'name'))
    rss_urls = get_cfg(sec, 'url').split(',')

    # Filter criteria from config
    filter_apply = get_cfg(sec, 'filter_apply')
    filter_type = get_cfg(sec, 'filter_type')
    filter_rule = get_cfg(sec, 'filter_rule')

    if not (filter_apply and filter_type and filter_rule):
        raise Exception('filter_apply, type, rule must be set together')

    max_items = int(get_cfg(sec, 'max_items', 0))
    
    # Read existing entries and truncate if necessary
    existing_entries = read_entry_from_file(sec)
    existing_entries = truncate_entries(existing_entries, max_entries=max_items)
    append_entries = []

    for rss_url in rss_urls:
        feed = feedparser.parse(rss_url)
        if feed.bozo:
            continue  # Skip malformed feeds

        for entry in feed.entries:
            if len(append_entries) >= max_items:
                break

            # Generate or retrieve necessary fields
            entry.title = entry.get('title', 'Untitled')
            entry.article = entry.get('content', [{}])[0].get('value', entry.get('description', entry.title))

            # Clean HTML content
            cleaned_article = clean_html(entry.article)
            
            # Apply filtering based on config
            if not filter_entry(entry, filter_apply, filter_type, filter_rule):
                continue

            # Summarize using GPT model
            entry.summary = gpt_summary(cleaned_article, model="gpt-3.5-turbo", language=language)
            append_entries.append(entry)

    # Output the summaries and links to a file
    with open(os.path.join(out_dir, 'summaries_and_links.txt'), 'w') as f:
        for entry in append_entries:
            summary_text = entry.summary if 'summary' in entry else 'No summary available'
            f.write(f"Summary: {summary_text}\nLink: {entry.link}\n\n")

config = configparser.ConfigParser()
config.read('config.ini')
secs = config.sections()
# Maxnumber of entries to in a feed.xml file
max_entries = 1000

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
U_NAME = os.environ.get('U_NAME')
OPENAI_PROXY = os.environ.get('OPENAI_PROXY')
OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
deployment_url = f'https://{U_NAME}.github.io/RSS-GPT/'
BASE =get_cfg('cfg', 'BASE')
keyword_length = int(get_cfg('cfg', 'keyword_length'))
summary_length = int(get_cfg('cfg', 'summary_length'))
language = get_cfg('cfg', 'language')

try:
    os.mkdir(BASE)
except:
    pass

feeds = []
links = []

for x in secs[1:]:
    output(x, language=language)
    feed = {"url": get_cfg(x, 'url').replace(',','<br>'), "name": get_cfg(x, 'name')}
    feeds.append(feed)  # for rendering index.html
    links.append("- "+ get_cfg(x, 'url').replace(',',', ') + " -> " + deployment_url + feed['name'] + ".xml\n")

def append_readme(readme, links):
    with open(readme, 'r') as f:
        readme_lines = f.readlines()
    while readme_lines[-1].startswith('- ') or readme_lines[-1] == '\n':
        readme_lines = readme_lines[:-1]  # remove 1 line from the end for each feed
    readme_lines.append('\n')
    readme_lines.extend(links)
    with open(readme, 'w') as f:
        f.writelines(readme_lines)

append_readme("README.md", links)
append_readme("README-zh.md", links)

# Rendering index.html used in my GitHub page, delete this if you don't need it.
# Modify template.html to change the style
with open(os.path.join(BASE, 'index.html'), 'w') as f:
    template = Template(open('template.html').read())
    html = template.render(update_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), feeds=feeds)
    f.write(html)
