import re
import os
import time
import random
import numpy as np
import pandas as pd
import cchardet as chardet
from itertools import islice
from threading import Thread, Lock
from queue import Queue
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup

class NewsScraper:
    def __init__(self, search_keyword, driver_path="./webdriver/chromedriver.exe", n_threads = 1, max_article_num = 200, min_word_cnt_per_article = 10, save_to_local = False, data_save_path="./data/"):
        """
            Initializes the NewsScraper with specified settings.

                @ search_keyword: The keyword to search for in news articles.
                @ driver_path: Path to the Chromedriver executable. Defaults to "./webdriver/chromedriver.exe".
                @ max_article_num: Maximum number of articles to scrape. Defaults to 200.
                @ min_word_cnt_per_article: Minimum word count per article for it to be considered valid. Defaults to 10 words.
                @ save_to_local: Boolean indicating whether to save the scraped data to a local file. Defaults to False.
                @ data_save_path: Path to save the scraped data if save_to_local is True. Defaults to "./data/".
        """
        # Driver setting
        options = webdriver.ChromeOptions()
        disable_image_video_loadings = {"profile.managed_default_content_settings.images": 2, "profile.managed_default_content_settings.videoes": 2}
        options.add_experimental_option("prefs", disable_image_video_loadings) 
        options.add_argument('headless')
        options.add_argument('log-level=3')

        # Intiate drivers and variables
        self.driver = {i:webdriver.Chrome(executable_path=driver_path, options=options) for i in range(n_threads)}
        self.threaded = n_threads > 1
        self.n_threads = n_threads
        self.save_path = data_save_path
        self.search_keyword = search_keyword
        self.save_to_local = save_to_local
        self.max_article_num = max_article_num
        self.min_word_cnt = min_word_cnt_per_article

        # Pre-store the search results of foxnews
        self.search_fox = []
    
    def search_foxnews(self, driver, verbose = True):
        """
        Searches Fox News for articles matching the initialized search keyword and retrieves their URLs.
        To display full search results, the driver first clicks 'Show More' button many times and then retreive the full search page html.

        :return: A list of URLs of the articles found.
        """
        # Retrieve urls of articles returned by search results
        search_url_prefix = "https://www.foxnews.com/search-results/search?q="
        if verbose: print("\nBegin searching on FoxNews...")
        driver.get(search_url_prefix+self.search_keyword)
        # Get full search results - 2 steps
        wait = WebDriverWait(driver, 30)
        # 1. first, click 'Show More' many times
        i = 0
        while i < int(self.max_article_num//10):
            try:
                # Scroll down to the bottom to avoid any pop-up windows blocking the 'show more' button
                # Get scroll height
                last_height = driver.execute_script("return document.body.scrollHeight")
                t = 0
                while t < 10:
                    # Scroll down to bottom
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    # Wait to load page
                    time.sleep(random.uniform(0.15, 0.2))
                    # Calculate new scroll height and compare with last scroll height
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        break
                    last_height = new_height
                    t += 1
                element = wait.until(EC.visibility_of_element_located((By.XPATH, "(//div[@class='button load-more'])[1]/a")))
                element.click()
                i += 1
            except TimeoutException:
                break
        # 2. then, copy down all that's now shown on the page
        search_result_soup = BeautifulSoup(driver.page_source, features="lxml")
        # Extract all links from the full page html
        article_links = list(set([link['href'] for link in search_result_soup.select("div.m > a")]))
        if verbose: print(f"Searching finished, {len(article_links)} articles found on FoxNews...")
        return article_links

    def search_cnn(self):
        """
        Searches CNN for articles matching the initialized search keyword and retrieves their URLs.
        To display full search results, the driver loops through all search pages and retrive a full list of article links.

        :return: A list of URLs of the articles found.
        """
        # Get search key and compose search query
        search_url_prefix = "https://www.cnn.com/search?q={}&from={}&size=10&page={}&sort=relevance&types=article&section="
        # Begin searching
        print("\nBegin searching on CNN...")

        # enter the search query in search page and make sure the number of search results presents
        page_results = None
        i = 0
        while page_results is None and i < 10:
            self.driver[0].get(search_url_prefix.format(self.search_keyword, 0, 1))
            time.sleep(1) # Allowing the initial JavaScript search result be generated properly
            page = BeautifulSoup(self.driver[0].page_source, features="lxml")
            page_results = page.find("div", {"class":"search__results-count"})
            i += 1
        num_results = int(re.findall('out of (\d+)', page_results.text)[0])
        article_links = [link["data-zjs-href"] for link in page.select("div.container__headline.container_list-images-with-description__headline > span.container__headline-text")]

        # start turning pages
        for i in range(1, min(num_results//10+1, int(self.max_article_num//10))):
            self.driver[0].get(search_url_prefix.format(self.search_keyword, i*10, i+1))
            time.sleep(1) # just in case the next page hasn't finished loading
            page = BeautifulSoup(self.driver[0].page_source, features="lxml")
            links = [link["data-zjs-href"] for link in page.select("div.container__headline.container_list-images-with-description__headline > span.container__headline-text")]
            article_links.extend(links)
        article_links = list(set(article_links))
        print(f"Searching finished, {len(article_links)} articles found on CNN...")

        return article_links

    def search_cnn_threaded(self):
        """
        Searches CNN for articles matching the initialized search keyword and retrieves their URLs.
        To display full search results, the driver loops through all search pages and retrive a full list of article links.

        :return: A list of URLs of the articles found.
        """
        # Get search key and compose search query
        search_url_prefix = "https://www.cnn.com/search?q={}&from={}&size=10&page={}&sort=relevance&types=article&section="
        # Begin searching
        print("\nBegin searching on CNN...")

        # enter the search query in search page and make sure the number of search results presents
        page_results = None
        i = 0
        while page_results is None and i < 10:
            self.driver[0].get(search_url_prefix.format(self.search_keyword, 0, 1))
            time.sleep(random.uniform(0.5, 1)) # Allowing the initial JavaScript search result be generated properly
            page = BeautifulSoup(self.driver[0].page_source, features="lxml")
            page_results = page.find("div", {"class":"search__results-count"})
            i += 1
        num_results = int(re.findall('out of (\d+)', page_results.text)[0])
        global article_links_cnn
        article_links_cnn = [link["data-zjs-href"] for link in page.select("div.container__headline.container_list-images-with-description__headline > span.container__headline-text")]

        # start turning pages - parallelized using multi-threading
        lock = Lock()
        def search_per_thread(q, driver):
            wait = WebDriverWait(driver, 2)
            while True:
                chunk = q.get()
                for i in chunk:
                    driver.get(search_url_prefix.format(self.search_keyword, i*10, i+1))
                    #time.sleep(0.75) # just in case the next page hasn't finished loading
                    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.container__headline.container_list-images-with-description__headline > span.container__headline-text")))
                    page = BeautifulSoup(driver.page_source, features="lxml")
                    links = [link["data-zjs-href"] for link in page.select("div.container__headline.container_list-images-with-description__headline > span.container__headline-text")]
                    lock.acquire()
                    article_links_cnn.extend(links)
                    lock.release()
                q.task_done()

        q = Queue()
        for i in range(self.n_threads):
            worker = Thread(target=search_per_thread, args=(q, self.driver[i], ), daemon=True)
            worker.start() 

        num_pages = min(num_results//10+1, int(self.max_article_num//10))
        chunk_size = (num_pages - 1) // self.n_threads + 1
        page_chunks = [list(islice(range(1, num_pages), i * chunk_size, (i + 1) * chunk_size)) for i in range(self.n_threads)]
        for chunk in page_chunks:
            q.put(chunk)

        q.join()
        print(f"Searching finished, {len(article_links_cnn)} articles found on CNN...")

        return article_links_cnn

    
    def scrape_foxnews(self):
        """
        Scrapes articles from Fox News based on URLs retrieved from the search_foxnews method. Extracts publication date, headline, 
        and main text of each article, checking for minimum word count and filtering out irrelevant content.

        :return: A pandas DataFrame containing scraped article details from Fox News.
        """
        # Iterate through the links
        article_links = self.search_foxnews(self.driver[0])
        article_content = []
        skipped_links = []
        skipped_cnt = 0
        junk_text = {"cyberguy.com", "click here"}
        print("\nBegin scraping on FoxNews...")
        # Get article contents from article urls
        for article_num, url in enumerate(article_links):

            # Get page
            self.driver[0].get(url)
            article_soup = BeautifulSoup(self.driver[0].page_source, features="lxml")

            # Header info extraction, if page has no content, skip this article
            header = article_soup.find("header", {"class":"article-header"})
            if header is None:
                print("\tArticle {} skipped due to invalid content - link: {}".format(article_num+1, url))
                skipped_cnt += 1
                skipped_links.append(url)
                continue
            
            # Meta information scraping
            publish_date = header.find("span",{"class":"article-date"}).text.strip("Published\n ").strip()
            headline = header.find("h1",{"class":"headline"}).text.strip().replace(u'\xa0', u' ')

            # Main Article Text scraping
            main_text = []
            for p in article_soup.select("div.article-body > p"):
                    sent = p.text.strip().replace(u'\xa0', u' ')
                    junk_sent_check = junk_text.intersection(set(sent.lower().split()))
                    if not (len(junk_sent_check) > 0 or sent.isupper()):
                        main_text.append(sent)
            main_text = " ".join(main_text).replace(u'\xa0', u' ').replace("  "," ").strip()

            # Check article validity
            if len(main_text) < self.min_word_cnt: 
                print("\tArticle {} skipped due to invalid content - link: {}".format(article_num+1, url))
                skipped_links.append(url)
                skipped_cnt += 1
                continue
            
            # Append article information to the list
            article_info = {
                "publish_date": publish_date,
                "headline": headline,
                "main_text": main_text,
                "media": "FoxNews",
                "type": "article",
                "url":url
            }
            article_content.append(article_info)
            #os.system('cls') # Clear screen
            print(f"\t{len(article_content)}/{len(article_links)} articles scraped, {skipped_cnt} skipped...")

        if skipped_cnt: print(f"Skipped links in FoxNews: {skipped_links}")

        # Parse scraped article infos to a dataframe
        df = pd.DataFrame(article_content)
        #print(df)

        # Save data to local
        if self.save_to_local: 
            df.to_excel(self.save_path+"foxnews.xlsx")
            print(f"FoxNews data saved to {self.save_path}foxnews.xlsx.")

        return df
    
    def scrape_cnn(self):
        """
        Scrapes articles from CNN based on URLs retrieved from the search_cnn method. Handles different content types, including live news 
        and regular articles, extracting publication date, headline, and main text. Checks for minimum word count and filters out irrelevant content.
        live-news articles are specially handled by forcing driver to scroll down to the page bottom and retrieve a full list of separate news.
        Note that each news blog in live-news is treated as an independent article and stored separately.

        :return: A pandas DataFrame containing scraped article details from CNN.
        """
        # Iterate through the links
        article_links = self.search_cnn()
        article_content = []
        skipped_links = []
        scraped_cnt, skipped_cnt = 0, 0
        junk_text = {}
        print("\nBegin scraping on CNN...")
        # Get article contents from article urls
        for article_num, url in enumerate(article_links):

            if "live-news" in url:

                try:
                    self.driver[0].get(url)

                    # Get scroll height
                    last_height = self.driver[0].execute_script("return document.body.scrollHeight")

                    i = 0
                    while i < 200:

                        # Scroll down to bottom
                        self.driver[0].execute_script("window.scrollTo(0, document.body.scrollHeight);")

                        # Wait to load page
                        time.sleep(0.5)

                        # Calculate new scroll height and compare with last scroll height
                        new_height = self.driver[0].execute_script("return document.body.scrollHeight")
                        if new_height == last_height:
                            break
                        last_height = new_height
                        i += 1

                except TimeoutException:
                    print("\tArticle {} skipped due to invalid content - link: {}".format(article_num+1, url))
                    skipped_cnt += 1
                    skipped_links.append(url)
                    continue

                article_soup = BeautifulSoup(self.driver[0].page_source, features="lxml")
                if article_soup is None:
                    print("\tArticle {} skipped due to invalid content - link: {}".format(article_num+1, url))
                    skipped_cnt += 1
                    skipped_links.append(url)
                    continue
                main_text_sec = article_soup.find("div",{"class":'live-story__items-container'})
                if main_text_sec is None:
                    main_text_sec = article_soup.find("div",{"id":'posts-and-button'})
                    if main_text_sec is None:
                        print("\tArticle {} skipped due to invalid content - link: {}".format(article_num+1, url))
                        skipped_cnt += 1
                        skipped_links.append(url)
                        continue
                articles = main_text_sec.find_all("article")
                num_skipped = 0
                for i in articles:
                    header = i.find("header")
                    headline = header.find("h2").text.strip().replace(u'\xa0', u' ')
                    publish_date = header.find("span").text.strip().replace(u'\xa0', u' ')
                    main_text = " ".join([i.text.strip().replace(u'\xa0', u' ') for i in i.select("div > p")]).replace("  ", " ")
                    if len(main_text) < self.min_word_cnt or headline is None or headline == "": continue
                    if "From CNN" in publish_date or publish_date is None or publish_date == "": num_skipped += 1; continue
                    article_info = {
                        "publish_date": publish_date,
                        "headline": headline,
                        "main_text": main_text,
                        "media": "CNN",
                        "type": "live-news",
                        "url":url
                    }
                    article_content.append(article_info)
                if num_skipped == len(articles): skipped_cnt += 1; skipped_links.append(url)
                scraped_cnt += 1
            
            elif "/reviews/" in url or "/cnn-underscored/" in url: # Promotions and advertisements of products
                print("\tArticle {} skipped due to irrelevant content - link: {}".format(article_num+1, url))
                skipped_cnt += 1
                continue

            else:
                
                self.driver[0].get(url)
                article_soup = BeautifulSoup(self.driver[0].page_source, features="lxml")

                header = article_soup.find("div", {"class":"headline headline--has-lowertext"})
                if header is None:
                    print("\tArticle {} skipped due to invalid content - link: {}".format(article_num+1, url))
                    skipped_links.append(url)
                    skipped_cnt += 1
                    continue
                
                # Meta Information scraping
                head_wrapper = header.find("div", {"class":"headline__wrapper"})
                headline = head_wrapper.find("h1", {"id":"maincontent"}).text.strip().replace(u'\xa0', u' ')
                head_footer_set = header.find("div", {"class":"headline__sub-text"})
                publish_date = head_footer_set.find("div", {"class":"timestamp"}).text.strip("Published Updated \n").replace(u'\xa0', u' ').replace("\n", "").replace("  "," ").replace("  "," ")

                # Main Article Text scraping
                main_text_sec = article_soup.find("div",{"class":"article__content"})
                main_text = [i.text.strip().replace(u'\xa0', u' ') for i in main_text_sec.find_all("p", {"class":"paragraph inline-placeholder"})]
                sub_header = [i.text.strip().replace(u'\xa0', u' ')+"." for i in main_text_sec.find_all("h2", {"class":"subheader"})]
                main_text = " ".join(main_text + sub_header).replace("  ", " ").replace('  ', ' ').strip()

                # Check article validity
                if len(main_text) < self.min_word_cnt: 
                    print("\tArticle {} skipped due to invalid content - link: {}".format(article_num+1, url))
                    skipped_links.append(url)
                    skipped_cnt += 1
                    continue

                # Append article information to the list
                article_info = {
                    "publish_date": publish_date,
                    "headline": headline,
                    "main_text": main_text,
                    "media": "CNN",
                    "type": "article",
                    "url":url
                }
                article_content.append(article_info)
                scraped_cnt += 1
            
            print(f"\t{scraped_cnt}/{len(article_links)} articles scraped, {skipped_cnt} skipped...")

        if skipped_cnt: print(f"Skipped links: {skipped_links}")

        # Parse scraped article infos to a dataframe
        df = pd.DataFrame(article_content)
        #print(df)

        # Save data to local
        if self.save_to_local: 
            df.to_excel(self.save_path+"cnn.xlsx")
            print(f"CNN data saved to {self.save_path}cnn.xlsx.")

        return df
    
    def scrape_foxnews_threaded(self):
        """
        Scrapes articles from Fox News based on URLs retrieved from the search_foxnews method. Extracts publication date, headline, 
        and main text of each article, checking for minimum word count and filtering out irrelevant content.

        :return: A pandas DataFrame containing scraped article details from Fox News.
        """
        # Iterate through the links
        global article_links, skipped_links, skipped_cnt, junk_text
        article_links = self.search_fox
        print(f"\nSearching Pre-loaded...{len(article_links)} articles found on FoxNews...")
        article_content = []
        skipped_links = []
        skipped_cnt = 0
        junk_text = {"cyberguy.com", "click here"}
        print("\nBegin scraping on FoxNews...")
        # Get article contents from article urls
        lock = Lock()
        def scrape_per_thread(q, driver):
            global skipped_cnt
            while True:
                chunk = q.get()
                for article_num, url in enumerate(chunk):

                    # Get page
                    try:
                        time.sleep(random.uniform(0.3, 0.7))
                        driver.get(url)
                        article_soup = BeautifulSoup(driver.page_source, features="lxml")
                    except TimeoutException:
                        print("\tArticle skipped due to invalid content - link: {}".format(url))
                        lock.acquire()
                        skipped_cnt += 1
                        skipped_links.append(url)
                        lock.release()
                        continue

                    # Header info extraction, if page has no content, skip this article
                    header = article_soup.find("header", {"class":"article-header"})
                    if header is None:
                        print("\tArticle skipped due to invalid content - link: {}".format(url))
                        lock.acquire()
                        skipped_cnt += 1
                        skipped_links.append(url)
                        lock.release()
                        continue
                    
                    # Meta information scraping
                    publish_date = header.find("span",{"class":"article-date"}).text.strip("Published\n ").strip()
                    headline = header.find("h1",{"class":"headline"}).text.strip().replace(u'\xa0', u' ')

                    # Main Article Text scraping
                    main_text = []
                    for p in article_soup.select("div.article-body > p"):
                        sent = p.text.strip()
                        if not any(junk.lower() in sent.lower() for junk in junk_text) and not sent.isupper():
                            main_text.append(sent)
                    main_text = re.sub(r'[\xa0]+|\s{2,}', ' ', ' '.join(main_text)).strip()

                    # Check article validity
                    if len(main_text) < self.min_word_cnt: 
                        print("\tArticle skipped due to invalid content - link: {}".format(url))
                        lock.acquire()
                        skipped_links.append(url)
                        skipped_cnt += 1
                        lock.release()
                        continue
                    
                    # Append article information to the list
                    article_info = {
                        "publish_date": publish_date,
                        "headline": headline,
                        "main_text": main_text,
                        "media": "FoxNews",
                        "type": "article",
                        "url":url
                    }
                    lock.acquire()
                    article_content.append(article_info)
                    lock.release()
                    #os.system('cls') # Clear screen
                    print(f"\t{len(article_content)}/{len(article_links)} articles scraped, {skipped_cnt} skipped...")
                q.task_done()

        # Multi-threading
        q = Queue()
        for i in range(self.n_threads):
            worker = Thread(target=scrape_per_thread, args=(q, self.driver[i], ), daemon=True)
            worker.start() 

        num_pages = len(article_links)
        chunk_size = num_pages // self.n_threads
        remainder = num_pages % self.n_threads
        page_chunks = [article_links[i * chunk_size + min(i, remainder) : (i + 1) * chunk_size + min(i + 1, remainder)] for i in range(self.n_threads)]
        for chunk in page_chunks:
            q.put(chunk)

        q.join()
        # After scraping
        if skipped_cnt: print(f"Skipped links in FoxNews: {skipped_links}")

        # Parse scraped article infos to a dataframe
        df = pd.DataFrame(article_content)
        #print(df)

        # Save data to local
        if self.save_to_local: 
            df.to_excel(self.save_path+"foxnews.xlsx")
            print(f"FoxNews data saved to {self.save_path}foxnews.xlsx.")

        return df
    
    def scrape_cnn_threaded(self):
        """
        Scrapes articles from CNN based on URLs retrieved from the search_cnn method. Handles different content types, including live news 
        and regular articles, extracting publication date, headline, and main text. Checks for minimum word count and filters out irrelevant content.
        live-news articles are specially handled by forcing driver to scroll down to the page bottom and retrieve a full list of separate news.
        Note that each news blog in live-news is treated as an independent article and stored separately.

        :return: A pandas DataFrame containing scraped article details from CNN.
        """
        # Iterate through the links
        global article_links, skipped_links, scraped_cnt, skipped_cnt
        article_links = self.search_cnn_threaded()
        article_content = []
        skipped_links = []
        scraped_cnt, skipped_cnt = 0, 0
        junk_text = {}
        print("\nBegin scraping on CNN...")

        lock = Lock()
        def scrape_per_thread(q, i, driver):
            while True:
                global scraped_cnt, skipped_cnt
                # Pre-load the search results for fox news using the last driver to do the job
                if i == self.n_threads-1: 
                    self.search_fox = self.search_foxnews(driver, verbose = False)
                # Other drivers scrape the articles
                else:
                    chunk = q.get()
                    # Get article contents from article urls
                    for article_num, url in enumerate(chunk):

                        if "live-news" in url:

                            try:
                                #time.sleep(random.uniform(0.05, 0.1))
                                driver.set_page_load_timeout(10)
                                driver.get(url)

                                # Get scroll height
                                last_height = driver.execute_script("return document.body.scrollHeight")

                                i = 0
                                while i < 100:

                                    # Scroll down to bottom
                                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

                                    # Wait to load page
                                    time.sleep(random.uniform(0.1, 0.2))

                                    # Calculate new scroll height and compare with last scroll height
                                    new_height = driver.execute_script("return document.body.scrollHeight")
                                    if new_height == last_height:
                                        break
                                    last_height = new_height
                                    i += 1

                            except TimeoutException:
                                print("\tArticle skipped due to invalid content - link: {}".format(url))
                                lock.acquire()
                                skipped_cnt += 1
                                skipped_links.append(url)
                                lock.release()
                                continue

                            article_soup = BeautifulSoup(driver.page_source, features="lxml")
                            if article_soup is None:
                                print("\tArticle skipped due to invalid content - link: {}".format(url))
                                lock.acquire()
                                skipped_cnt += 1
                                skipped_links.append(url)
                                lock.release()
                                continue
                            main_text_sec = article_soup.find("div",{"class":'live-story__items-container'})
                            if main_text_sec is None:
                                main_text_sec = article_soup.find("div",{"id":'posts-and-button'})
                                if main_text_sec is None:
                                    print("\tArticle {} skipped due to invalid content - link: {}".format(article_num+1, url))
                                    lock.acquire()
                                    skipped_cnt += 1
                                    skipped_links.append(url)
                                    lock.release()
                                    continue
                            articles = main_text_sec.find_all("article")
                            num_skipped = 0
                            for i in articles:
                                header = i.find("header")
                                headline = header.find("h2").text.strip().replace(u'\xa0', u' ')
                                publish_date = header.find("span").text.strip().replace(u'\xa0', u' ')
                                main_text = re.sub(r'[\xa0\n\t]+|\s{2,}', ' ', " ".join([i.text for i in i.select("div > p")])).replace("  "," ").strip()
                                if len(main_text) < self.min_word_cnt or headline is None or headline == "": continue
                                if "From CNN" in publish_date or publish_date is None or publish_date == "": lock.acquire(); num_skipped += 1; lock.release(); continue
                                article_info = {
                                    "publish_date": publish_date,
                                    "headline": headline,
                                    "main_text": main_text,
                                    "media": "CNN",
                                    "type": "live-news",
                                    "url":url
                                }
                                lock.acquire()
                                article_content.append(article_info)
                                lock.release()
                            if num_skipped == len(articles): lock.acquire(); skipped_cnt += 1; skipped_links.append(url); lock.release()
                            lock.acquire()
                            scraped_cnt += 1
                            lock.release()
                        
                        elif "/reviews/" in url or "/cnn-underscored/" in url: # Promotions and advertisements of products
                            print("\tArticle skipped due to irrelevant content - link: {}".format(url))
                            lock.acquire()
                            skipped_cnt += 1
                            skipped_links.append(url)
                            lock.release()
                            continue

                        else:
                            #time.sleep(random.uniform(0.25, 0.5))
                            try:
                                driver.set_page_load_timeout(15)
                                driver.get(url)
                                article_soup = BeautifulSoup(driver.page_source, features="lxml")
                            except TimeoutException:
                                print("\tArticle skipped due to invalid content - link: {}".format(url))
                                lock.acquire()
                                skipped_cnt += 1
                                skipped_links.append(url)
                                lock.release()
                                continue

                            header = article_soup.find("div", {"class":"headline headline--has-lowertext"})
                            if header is None:
                                print("\tArticle skipped due to invalid content - link: {}".format(url))
                                lock.acquire()
                                skipped_links.append(url)
                                skipped_cnt += 1
                                lock.release()
                                continue
                            
                            # Meta Information scraping
                            head_wrapper = header.find("div", {"class":"headline__wrapper"})
                            headline = head_wrapper.find("h1", {"id":"maincontent"}).text.strip().replace(u'\xa0', u' ')
                            head_footer_set = header.find("div", {"class":"headline__sub-text"})
                            publish_date = re.sub(r'^(Published|Updated|\n|\s)+|[\xa0\n]+|\s{2,}', ' ', head_footer_set.find("div", {"class":"timestamp"}).text).strip()

                            # Main Article Text scraping
                            main_text_sec = article_soup.find("div",{"class":"article__content"})
                            main_text = [i.text for i in main_text_sec.find_all("p", {"class":"paragraph inline-placeholder"})]
                            main_text = re.sub(r'[\xa0\n\t]+|\s{2,}', ' ', " ".join(main_text)).replace("  "," ").strip()

                            # Check article validity
                            if len(main_text) < self.min_word_cnt: 
                                print("\tArticle skipped due to invalid content - link: {}".format(url))
                                lock.acquire()
                                skipped_links.append(url)
                                skipped_cnt += 1
                                lock.release()
                                continue

                            # Append article information to the list
                            article_info = {
                                "publish_date": publish_date,
                                "headline": headline,
                                "main_text": main_text,
                                "media": "CNN",
                                "type": "article",
                                "url":url
                            }
                            lock.acquire()
                            article_content.append(article_info)
                            scraped_cnt += 1
                            lock.release()
                        
                        print(f"\t{scraped_cnt}/{len(article_links)} articles scraped, {skipped_cnt} skipped...")
                    q.task_done()

        # Multi-threading
        q = Queue()
        for i in range(self.n_threads):
            worker = Thread(target=scrape_per_thread, args=(q, i, self.driver[i], ), daemon=True)
            worker.start() 

        num_pages = len(article_links)
        chunk_size = num_pages // (self.n_threads-1)
        remainder = num_pages % (self.n_threads-1)
        page_chunks = [article_links[i * chunk_size + min(i, remainder) : (i + 1) * chunk_size + min(i + 1, remainder)] for i in range(self.n_threads-1)]

        # Redistribute chunk size and set less space for the last chunk
        # page_chunks = [article_links[i * chunk_size + min(i, remainder) : (i + 1) * chunk_size + min(i + 1, remainder)] for i in range(self.n_threads - 1)]
        # last_chunk = article_links[(self.n_threads - 1) * chunk_size + remainder:]
        # page_chunks.append(last_chunk)

        for chunk in page_chunks:
            q.put(chunk)

        q.join()

        # Scraping finished
        if skipped_cnt: print(f"Skipped links: {skipped_links}")

        # Parse scraped article infos to a dataframe
        df = pd.DataFrame(article_content)
        #print(df)

        # Save data to local
        if self.save_to_local: 
            df.to_excel(self.save_path+"cnn.xlsx")
            print(f"CNN data saved to {self.save_path}cnn.xlsx.")

        return df

    def close(self):
        """
        Closes the web browser session controlled by the webdriver.
        """
        for i in range(self.n_threads):
            self.driver[i].close()



if __name__ == "__main__":

    # Get Search Keyword
    search_key = input("Enter search keyword of your interest: ")

    # Start scraper
    start_time = time.time()
    scraper = NewsScraper(search_keyword=search_key, driver_path="./webdriver/chromedriver.exe", n_threads = 17, max_article_num = 300, min_word_cnt_per_article = 10, save_to_local = True, data_save_path="./data/")

    # Scrape FoxNews and CNN
    cnn_df = scraper.scrape_cnn_threaded()
    foxnews_df = scraper.scrape_foxnews_threaded()

    # Close the scraper after usage
    scraper.close()
    print(f"\nScraping completed - {time.time()-start_time:.2f}s")
