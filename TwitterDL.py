# -*- coding: utf-8 -*
	"""
	This is a simple Twitter bot that downloads all media from users you follow 
	and sends an email alert when finished. Tweet ID's are stored in an sqlite database so that
	you can delete the content from your downloads folder without worrying about re-downloading them again.
	
	Ideally, you set it as a cronjob for your server to run every x hours.
	
	Usage: edit the config.cfg and run with python TwitterDL.py
	blacklist.txt is for users who you follow, but do not wish to download content from.
	
	"""
	
import os
import sys

MIN_PYTHON = (3,6)
if sys.version_info < MIN_PYTHON:
    sys.exit("Python %s.%s or later is required.\n" % MIN_PYTHON)
	
import configparser
import operator
import json
import urllib.parse
import sqlite3
import time

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import tweepy
from tweepy import OAuthHandler

import urllib.request
from urllib.error import HTTPError

from datetime import datetime
import colorama
from colorama import Fore

def path(filename):
	return os.path.join(current_path,filename)
			
class TwitterAuth:
	"""
	Tweepy auth setup.
	"""
	def parsedconfig(config_file):
		config = configparser.ConfigParser()
		config.read(config_file)
		return config 
		
	def authorise_twitter_api(config):
	  auth = OAuthHandler(config['DEFAULT']['consumer_key'], config['DEFAULT']['consumer_secret'])
	  auth.set_access_token(config['DEFAULT']['access_token'], config['DEFAULT']['access_secret'])
	  return auth
	  
class TwitterDL:
	"""
	Main class for twitterDL functions.
	"""
	
	userlist = ['FakeryWay']
	retry = False
	retrycount = 0
	current_user = ""
	db = None

	def __init__(self):	
		self.AddFollowers()
		
	def AddFollowers(self):
		print('Fetching followers...')
		blacklist = [line.rstrip('\n') for line in open(path('blacklist.txt'))]
		self.userlist = [x._json['screen_name'] for x in tweepy.Cursor(api.friends).items() if x._json['screen_name'] not in blacklist]
		self._initDB()
		
	def _initDB(self):
		dbpath =path('dat.db')
		dbExists = os.path.isfile(dbpath) and os.access(dbpath,os.R_OK)
	
		if not dbExists: 
			sqlDB = sqlite3.connect( dbpath, isolation_level = None, detect_types = sqlite3.PARSE_DECLTYPES )	   
			self.db = sqlDB.cursor()
			self.db.execute( 'CREATE TABLE history ( id INTEGER, url TEXT,user TEXT, PRIMARY KEY( id, url,user ) );' )
			self.db.execute( 'CREATE TABLE jobcount ( count INTEGER );' )
			self.db.execute( 'CREATE INDEX history_id_index ON history ( id );' )
			self.db.execute( 'INSERT INTO jobcount (count ) VALUES ( ? );', (  '0'  ))
		else:
			sqlDB = sqlite3.connect( dbpath, isolation_level = None, detect_types = sqlite3.PARSE_DECLTYPES )	   
			self.db = sqlDB.cursor()
			
		self.process_users()
				
	def process_users(self):

		#Incase it fails(Usually too many downloads), wait awhile then retry up to 5 times)
		try:
			if self.retry:
				index = self.userlist.index(self.current_user)
				for user in self.userlist[index:]:
					self.current_user = user
					self.tweepyFetch()
					time.sleep(6)
			else:
				for user in self.userlist:
					self.current_user = user
					self.tweepyFetch()
					time.sleep(6)
						
		except Exception as e:
			print("Retrying with "+self.current_user)
			time.sleep(120)
			self.retrycount = self.retrycount+1
			if self.retrycount < 6:
				retry = True			
				process_users()
			else:
				print("Retry count exceeded limit,closing.")
				sys.exit()

		#Update job count for email notification.
		jobcount = str(int(self.db.execute("SELECT count FROM jobcount").fetchone()[0])+1)
		self.db.execute("UPDATE jobcount SET count ="+jobcount)
		
		
		self.email(jobcount)
		print("All jobs finished. Closing.")
		sys.exit()
	
	def email(self,jobcount):
		#timestamp
		year, month, day, hour, minute,noon = time.strftime("%Y,%m,%d,%I,%M,%p").split(',')
		timestamp = "%s:%s %s [%s/%s/%s]" % (hour,minute,noon,month,day,year)	

		#prepare html
		htmlFile = open(path("template.html"), 'r', encoding='utf-8')
		source = htmlFile.read()
		source = source.replace("<JOBCOUNT>",jobcount)
		source = source.replace("<TIMESTAMP>",timestamp)

		gmail_user = str(config['EMAIL']['email_address'])
		gmail_password = str(config['EMAIL']['app_pass'])
		
		sent_from = str(config['EMAIL']['from_address'])
		to = str(config['EMAIL']['email_address'])

		subject = '[TwitterDL] - Job #'+jobcount+' completed! <3'
		msg = MIMEMultipart('alternative')
		msg['Subject'] = subject
		msg['From'] = sent_from
		msg['To'] = to
		text = 'Subscription completed task at '+timestamp
		html = source	
		msg.attach(MIMEText(text, 'plain'))
		msg.attach(MIMEText(html, 'html'))
		try:
			server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
			server.ehlo()
			server.login(gmail_user, gmail_password)
			server.sendmail(sent_from, to, msg.as_string())
			server.close()
			print('\nEmail Sent!')
		except:
			print('\nEmail failed to send. Internet not working?')
			
	def tweepyFetch(self):
		output_folder = os.path.join(download_dir,self.current_user)
		newuser = False
		
		if not os.path.exists(output_folder):
			newuser = True
			print(Fore.RED + "New User:{0}".format(self.current_user))
			os.makedirs(output_folder)
					
		#If a new Twitter user is added, grab everything, otherwise get check for the first 50 tweets.(Reduces unnecessary API calls)
		limit = 10000 if newuser else tweetLimit
		
		try:
			status = tweepy.Cursor(api.user_timeline, screen_name=self.current_user, include_rts=False, exclude_replies=False, include_entities=True,tweet_mode='extended').items(limit)
		except TweepyError:
			print(Fore.RED + "Check if {0} exists or has been suspended. Skipping".format(self.current_user))
			pass
			
		for i, tweet_status in enumerate(status):
			sys.stdout.write(Fore.BLUE+"\r%s[%s/%s)]" % (self.current_user,str(i),str(limit) ))
			sys.stdout.flush()
			self.tweet_media_urls(tweet_status,output_folder)
		
	# It returns [] if the tweet doesn't have any media
	def tweet_media_urls(self,tweet_status,output_folder):
		media = tweet_status._json.get('extended_entities', {}).get('media', [])
		bitratedict = {}
		count = 0
		urllist = []
		
		#Return if no media found
		if (len(media) == 0):
			return []
		else:		
			for item in media:
				#Get highest quality video url
				status_id =int( item['expanded_url'].split('/')[5])
				
				#Return if Tweet ID exists in DB.
				for row in self.db.execute("SELECT id FROM history WHERE id=?", (status_id,)):
					return []
				else:	
					self.db.execute( 'INSERT INTO history ( id, url, user ) VALUES ( ?, ?, ? );', ( ( status_id,item['media_url'], self.current_user) ) )
					print(Fore.YELLOW + " DL:{0}#{1}".format(self.current_user, str(status_id)))
					if 'video_info' in item:
						for info in item['video_info']['variants']:
							if 'bitrate' in info:
								count = count+1
								bitratedict[count] = info
						video_url= max(bitratedict.values(), key = lambda k: k['bitrate'])['url']
						urllist.append(video_url)
					else:
						urllist.append(item['media_url'])
		for url in urllist:
			file_name = os.path.split(url)[1]
			if '?tag' in file_name:
				#remove tag text from url
				toreplace = re.search(r'\?tag.*',file_name).group(0) 
				file_name = file_name.replace(toreplace,"")
			ext = os.path.splitext(file_name)[1].lower()
			fullpath = os.path.join(output_folder, file_name)

			def download(url):
				try:
					urllib.request.urlretrieve(url , fullpath)
				except HTTPError as e:
					print(e.read())
					time.sleep(60)
					download(url)
				
			if not os.path.exists(fullpath):
				if ext == '.mp4':			
					download(url)
				else:
					download(url +":orig")					
		return []
					
current_path = os.path.dirname(os.path.realpath(__file__))
config_path = path('config.cfg')
config = TwitterAuth.parsedconfig(config_path)
download_dir = config['DOWNLOADING']['download_folder']
tweetLimit = int(config['DOWNLOADING']['tweet_limit'])
auth = TwitterAuth.authorise_twitter_api(config)
api = tweepy.API(auth, wait_on_rate_limit=True)	
colorama.init(autoreset=True)

if __name__=='__main__':
	TwitterAuth()
	TwitterDL()
