import config
import json
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from threading import Timer
from os.path import isfile
from time import time
from fuzzywuzzy import fuzz
from colorama import init, Fore
from sys import exit

class Bot(vk_api.VkApi):

	def __init__(self, interval):

		super().__init__(token=config.group_token, api_version=config.api_version)
		init()

		self.interval = interval

		self.warned_users = {}
		self.muted_users = {}
		self.antispam_dict = {}

		self.cache_files = ((self.warned_users, 'warned_users.json'), (self.muted_users, 'muted_users.json'), (self.antispam_dict, 'antispam_dict.json'))

	def __enter__(self):

		if not all((isfile(self.cache_files[0][1]), isfile(self.cache_files[1][1]), isfile(self.cache_files[2][1]))):
			
			print((f'{Fore.YELLOW}[ WARNING ]\n'
				   f'{Fore.WHITE}Cache files was not founded\n'))	
		
			self._clear_antispam_dict()

		else:

			for dictionary, filename in self.cache_files:
				with open(filename, 'r') as file:
					dictionary.update(json.load(file))

		return self

	def __exit__(self, *args):

		print((f'{Fore.YELLOW}[ NOTIFICATION ]\n'
			   f'{Fore.WHITE}Saving cache files...\n'))

		for dictionary, filename in self.cache_files:
			with open(filename, 'w') as file:
				file.write(json.dumps(dictionary))

		print((f'{Fore.YELLOW}[ NOTIFICATION ]\n'
			   f'{Fore.WHITE}Bot was shutdowned\n'))

		raise SystemExit

	def __check_messages(self):

		print((f'{Fore.YELLOW}[ NOTIFICATION ]\n'
			   f'{Fore.WHITE}Bot was started\n'))

		longpoll = VkBotLongPoll(self, config.group_id)

		for event in longpoll.listen():
			if event.type == VkBotEventType.MESSAGE_NEW and event.from_chat:

				user_id, chat_id, message_id, text = event.message.from_id, event.chat_id, event.message.conversation_message_id, event.message.text 

				print((f'{Fore.WHITE}[ NEW MESSAGE ]\n'
					   f'{Fore.RED}From user: {Fore.WHITE}{user_id}\n'
					   f'{Fore.BLUE}From chat: {Fore.WHITE}{chat_id}\n'
					   f'{Fore.GREEN}Message id: {Fore.WHITE}{message_id}\n'
					   f'{Fore.YELLOW}Message text: {Fore.WHITE}{text}\n'))

				self._treat_message(str(user_id), chat_id, message_id, text, event)

	def _treat_message(self, user_id, chat_id, message_id, text, event):

		if user_id in self.muted_users:
			if time() > self.muted_users[user_id]:
				self.muted_users.pop(user_id)
			else:
				try:
					self.method('messages.delete', {
													'peer_id' : 2000000000 + chat_id,
													'conversation_message_ids' : [message_id],
													'delete_for_all' : 1
												   })
				except Exception:
					pass

				return

		if not text:
			return

		if text.startswith('!') and user_id in config.bot_admins:
			self._execute_command(chat_id, message_id, text[1:], event)
		else:
			if user_id not in config.bot_admins:
				try:
					self._control_spam(user_id, chat_id, message_id, text)
				except Exception:
					pass

	def _execute_command(self, chat_id, message_id, text, event):

		if text == 'кик собак':
			self._kick_dogs(chat_id, text)
		elif text == 'размут':
			self._unmute_user(str(event.object['message']['reply_message']['from_id']), chat_id)
		elif text == 'мут':
			self._mute_user(str(event.object['message']['reply_message']['from_id']), chat_id)
		elif text == 'варн' or text == 'пред':
			self._warn_user(str(event.object['message']['reply_message']['from_id']), chat_id)
		elif text == 'анварн' or text == 'разпред':
			self._unwarn_user(str(event.object['message']['reply_message']['from_id']), chat_id)
		else:
			forward = json.dumps({
					   'peer_id' : 2000000000 + chat_id,
					   'conversation_message_ids' : message_id,
					   'is_reply' : True
					  })

			self._send_message(chat_id=chat_id, forward=forward, message='таких команд не знаю')

	def _unmute_user(self, user_id, chat_id):

		try:
			self.muted_users.pop(user_id)
			print((f'{Fore.YELLOW}[ NOTIFICATION ]\n'
				   f'{Fore.WHITE}{user_id} unmuted\n'))
			self._send_message(peer_id=2000000000+chat_id, message=f'@id{user_id} размучен')
		except KeyError:
			pass

	def _kick_dogs(self, chat_id, text):

		if text == 'кик собак':

			members_list = []

			members_count = self.method('messages.getConversationMembers', {
																			'peer_id' : 2000000000 + chat_id, 
																			'count' : 1
																		   })['count']

			for query in range((members_count // 50) + 1):

				members_list_data = self.method('messages.getConversationMembers', {
																					'peer_id' : 2000000000 + chat_id, 
																					'count' : 50, 
																					'offset' : query * 50
																				   })['items']

				for member in members_list_data:
					member_id = member['member_id']
					if member_id >= 0:
						members_list.append(member_id)

			kicked_users = 0
			for id in members_list:
				user_info = self.method('users.get', {'user_ids' : id})
				try:
					status = user_info[0]['deactivated']
				except KeyError:
					pass
				else:
					if status == 'deleted':
						try:
							self.method('messages.removeChatUser', {
																	'user_id' : id, 
																	'chat_id' : chat_id
																   })
							kicked_users += 1
						except vk_api.exceptions.ApiError:
							pass

			print((f'{Fore.YELLOW}[ NOTIFICATION ]\n'
				   f'{Fore.WHITE}{kicked_users} dogs was kicked\n'))

			self._send_message(peer_id=2000000000+chat_id, message=f'кикнуто {kicked_users} собак')

	def _control_spam(self, user_id, chat_id, message_id, text):

		if user_id not in self.antispam_dict:
			self.antispam_dict.update({user_id : [[text, time()]]})
			return

		if len(self.antispam_dict[user_id]) < 3:
			self.antispam_dict[user_id].append([text, time()])
		else:
			time_list = []
			for message_data in self.antispam_dict[user_id]:
				time_list.append(message_data[1])

			oldest_message = min(time_list)

			# ratio at first
			for message_data in self.antispam_dict[user_id]:
				match_percent = fuzz.ratio(text, message_data[0])
				if match_percent >= 90:
					self._warn_user(user_id, chat_id)
					break

			# then add message
			message_data_index = 0

			for message_data in self.antispam_dict[user_id]:

				if message_data[1] == oldest_message:
					self.antispam_dict[user_id][message_data_index] = [text, time()]

				message_data_index += 1

	def _clear_antispam_dict(self):

		Timer(interval=self.interval, function=self._clear_antispam_dict).start()

		self.antispam_dict.clear()

	def _unwarn_user(self, user_id, chat_id):

		user_warns = self.warned_users[user_id]		

		if user_warns > 1:
			user_warns -= 1
			self.warned_users[user_id] = user_warns
		else:
			try:
				self.warned_users.pop(user_id)
			except KeyError:
				pass

		print((f'{Fore.YELLOW}[ NOTIFICATION ]\n'
			   f'{Fore.WHITE}{user_id} was unwarned\n'))

		self._send_message(peer_id=2000000000+chat_id, message=f'@id{user_id} снято предупреждение ({self.warned_users[user_id]} / 3 предупреждений)')

	def _warn_user(self, user_id, chat_id):
		
		if user_id not in self.warned_users:
			self.warned_users.update({user_id : 1})
			self._send_message(peer_id=2000000000+chat_id, message=f'@id{user_id} выдано 1 / 3 предупреждений')
			return
		else:
			self.warned_users[user_id] += 1
			self._send_message(peer_id=2000000000+chat_id, message=f'@id{user_id} выдано {self.warned_users[user_id]} / 3 предупреждений')

		print((f'{Fore.YELLOW}[ NOTIFICATION ]\n'
			   f'{Fore.WHITE}{user_id} was warned\n'))

		if self.warned_users[user_id] == 3:
			self.warned_users.pop(user_id)
			self._mute_user(user_id, chat_id)

	def _mute_user(self, user_id, chat_id):

		self.muted_users.update({user_id : time() + 24 * 60 * 60})

		print((f'{Fore.YELLOW}[ NOTIFICATION ]\n'
			   f'{Fore.WHITE}{user_id} was muted\n'))

		self._send_message(peer_id=2000000000+chat_id, message=f'@id{user_id} выдан мут на 24 часа')

	def _send_message(self, **kwargs):

		kwargs.update({
					   'random_id' : 0
			          })

		self.method('messages.send', kwargs)

	def start(self):

		self.__check_messages()

if __name__ == '__main__':

	try:
		interval = 60 * 15
		with Bot(interval) as bot:
			bot.start()
	except (KeyboardInterrupt, SystemExit):
		exit()
