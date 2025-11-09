import json
import time
import requests
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from datetime import datetime
import logging
import threading

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = "7527777777:AAEbOccccbEZc1ck.........."

# Файлы для хранения данных
WALLETS_FILE = "look_wallet.json"
LAST_TX_FILE = "last_transactions.json"
SETTINGS_FILE = "chat_settings.json"

# API URLs
TON_API_URL = "https://toncenter.com/api/v3/transactions"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
API_HEADERS = {'accept': 'application/json'}

class WalletMonitor:
    def __init__(self):
        self.wallets = self.load_wallets()
        self.last_transactions = self.load_last_transactions()
        self.chat_settings = self.load_chat_settings()
        self.bot_start_time = datetime.now()
        self.first_run = True  # Флаг первого запуска
    
    def load_wallets(self):
        """Загрузка списка кошельков из файла"""
        try:
            with open(WALLETS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def load_last_transactions(self):
        """Загрузка последних транзакций из файла"""
        try:
            with open(LAST_TX_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def load_chat_settings(self):
        """Загрузка настроек чатов"""
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def save_wallets(self):
        """Сохранение списка кошельков в файл"""
        with open(WALLETS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.wallets, f, ensure_ascii=False, indent=2)
    
    def save_last_transactions(self):
        """Сохранение последних транзакций в файл"""
        with open(LAST_TX_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.last_transactions, f, ensure_ascii=False, indent=2)
    
    def save_chat_settings(self):
        """Сохранение настроек чатов"""
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.chat_settings, f, ensure_ascii=False, indent=2)
    
    def initialize_chat_settings(self, chat_id):
        """Инициализация настроек для чата"""
        if str(chat_id) not in self.chat_settings:
            self.chat_settings[str(chat_id)] = {
                'notifications': True,
                'created_at': datetime.now().isoformat()
            }
            self.save_chat_settings()
    
    def add_wallet(self, chat_id, wallet_address, chat_type):
        """Добавление кошелька для мониторинга"""
        self.initialize_chat_settings(chat_id)
        
        # Нормализуем адрес кошелька
        wallet_address = wallet_address.strip()
        
        if wallet_address not in self.wallets:
            self.wallets[wallet_address] = []
        
        # Проверяем, не добавлен ли уже этот чат для этого кошелька
        chat_exists = any(chat['chat_id'] == str(chat_id) for chat in self.wallets[wallet_address])
        
        if not chat_exists:
            self.wallets[wallet_address].append({
                'chat_id': str(chat_id),
                'chat_type': chat_type,
                'added_at': datetime.now().isoformat()
            })
            self.save_wallets()
            return True
        return False
    
    def remove_wallet(self, chat_id, wallet_address):
        """Удаление кошелька из мониторинга для конкретного чата"""
        wallet_address = wallet_address.strip()
        
        if wallet_address in self.wallets:
            # Удаляем только этот чат из списка отслеживания кошелька
            self.wallets[wallet_address] = [
                chat for chat in self.wallets[wallet_address] 
                if chat['chat_id'] != str(chat_id)
            ]
            
            # Если больше никто не отслеживает этот кошелек, удаляем его полностью
            if not self.wallets[wallet_address]:
                del self.wallets[wallet_address]
                if wallet_address in self.last_transactions:
                    del self.last_transactions[wallet_address]
            
            self.save_wallets()
            self.save_last_transactions()
            return True
        return False
    
    def get_chat_wallets(self, chat_id):
        """Получение списка кошельков для конкретного чата"""
        chat_wallets = []
        for wallet, chats in self.wallets.items():
            if any(chat['chat_id'] == str(chat_id) for chat in chats):
                chat_wallets.append(wallet)
        return chat_wallets
    
    def set_notifications(self, chat_id, status):
        """Включение/выключение уведомлений для чата"""
        self.initialize_chat_settings(chat_id)
        self.chat_settings[str(chat_id)]['notifications'] = status
        self.save_chat_settings()
        return status
    
    def get_notifications_status(self, chat_id):
        """Получение статуса уведомлений для чата"""
        self.initialize_chat_settings(chat_id)
        return self.chat_settings[str(chat_id)]['notifications']
    
    def format_wallet_list(self, chat_id):
        """Форматирование списка кошельков для отображения"""
        wallets = self.get_chat_wallets(chat_id)
        if not wallets:
            return "📭 *Список кошельков пуст*\n\nДобавьте кошельки командой /addwallet"
        
        message = "👛 *Отслеживаемые кошельки:*\n\n"
        for i, wallet in enumerate(wallets, 1):
            message += f"{i}. `{wallet}`\n\n"
        
        message += "🗑 *Удалить кошелек:* /removewallet <адрес>"
        return message
    
    def format_transaction_info(self, transaction, address_book):
        """Форматирование информации о транзакции"""
        try:
            in_msg = transaction.get('in_msg', {})
            out_msgs = transaction.get('out_msgs', [])
            
            # Определяем тип транзакции
            if in_msg.get('source') and in_msg.get('destination'):
                tx_type = "📥 Входящая"
                amount = in_msg.get('value', '0')
                from_addr = in_msg.get('source', 'Неизвестно')
                to_addr = in_msg.get('destination', 'Неизвестно')
                
                # Получаем комментарий для входящей транзакции
                comment = self.extract_comment(in_msg)
                
            elif out_msgs:
                tx_type = "📤 Исходящая"
                first_out_msg = out_msgs[0]
                amount = first_out_msg.get('value', '0')
                from_addr = transaction.get('account', 'Неизвестно')
                to_addr = first_out_msg.get('destination', 'Неизвестно')
                
                # Получаем комментарий для исходящей транзакции
                comment = self.extract_comment(first_out_msg)
            else:
                tx_type = "🔁 Другая"
                amount = '0'
                from_addr = 'Неизвестно'
                to_addr = 'Неизвестно'
                comment = ""
            
            # Конвертируем наноТОН в TON
            try:
                amount_ton = int(amount) / 1e9
                amount_str = f"{amount_ton:.4f} TON"
            except:
                amount_str = f"{amount} наноТОН"
            
            # Форматируем адреса с доменами и user-friendly форматом
            def format_address_with_link(addr):
                if addr == 'Неизвестно':
                    return addr
                
                # Ищем в address_book
                address_info = address_book.get(addr, {})
                user_friendly = address_info.get('user_friendly', addr)
                
                # Определяем тип адреса по префиксу
                if user_friendly.startswith('EQ'):
                    addr_type = "EQ"
                elif user_friendly.startswith('UQ'):
                    addr_type = "UQ" 
                elif user_friendly.startswith('0:'):
                    addr_type = "RAW"
                else:
                    addr_type = "UNK"
                
                # Берем только первые 6 и последние 4 символа для отображения
                if len(user_friendly) > 10:
                    short_addr = user_friendly[:6] + "..." + user_friendly[-4:]
                else:
                    short_addr = user_friendly
                
                domain = address_info.get('domain')
                
                if domain:
                    display_text = f"{domain} ({addr_type}:{short_addr})"
                else:
                    display_text = f"{addr_type}:{short_addr}"
                
                # Создаем ссылку на tonviewer
                tonviewer_url = f"https://tonviewer.com/{user_friendly}"
                
                return f"[{display_text}]({tonviewer_url})"
            
            message = f"""
{tx_type}
💎 *Сумма:* {amount_str}
👤 *От:* {format_address_with_link(from_addr)}
🎯 *Кому:* {format_address_with_link(to_addr)}
⏰ *Время:* {datetime.fromtimestamp(transaction.get('now', 0)).strftime('%d.%m.%Y %H:%M:%S')}
"""
            
            # Добавляем комментарий только если он есть
            if comment:
                message += f"💬 *Комментарий:* {comment}\n"
            
            return message.strip()
            
        except Exception as e:
            logger.error(f"Ошибка форматирования транзакции: {e}")
            return f"❌ Ошибка обработки транзакции: {str(e)}"
    
    def extract_comment(self, message_data):
        """Извлечение комментария из сообщения (входящего или исходящего)"""
        try:
            if not message_data:
                return ""
            
            message_content = message_data.get('message_content', {})
            decoded = message_content.get('decoded', {})
            
            if decoded.get('type') == 'text_comment':
                return decoded.get('comment', '')
            
            return ""
        except Exception as e:
            logger.error(f"Ошибка извлечения комментария: {e}")
            return ""
    
    def check_transactions_sync(self):
        """Синхронная версия проверки транзакций"""
        try:
            all_wallets = list(self.wallets.keys())
            if not all_wallets:
                logger.info("Нет кошельков для проверки")
                return
            
            logger.info(f"Проверяем транзакции для {len(all_wallets)} кошельков...")
            
            # Проверяем каждый кошелек отдельно
            for wallet in all_wallets:
                try:
                    url = f"{TON_API_URL}?account={wallet}&limit=10&offset=0&sort=desc"
                    
                    logger.info(f"Запрос для кошелька: {wallet[:8]}...")
                    
                    response = requests.get(url, headers=API_HEADERS, timeout=30)
                    
                    if response.status_code == 200:
                        data = response.json()
                        transactions = data.get('transactions', [])
                        address_book = data.get('address_book', {})
                        
                        if transactions:
                            logger.info(f"Найдено {len(transactions)} транзакций для {wallet[:8]}...")
                            # Обрабатываем транзакции для этого кошелька
                            self.process_transactions_for_wallet(wallet, transactions, address_book)
                        else:
                            logger.info(f"Нет новых транзакций для {wallet[:8]}...")
                    else:
                        logger.error(f"Ошибка API для {wallet[:8]}: {response.status_code}")
                    
                    # Пауза между запросами
                    time.sleep(1)
                    
                except requests.RequestException as e:
                    logger.error(f"Ошибка запроса для {wallet[:8]}: {e}")
                except Exception as e:
                    logger.error(f"Общая ошибка для {wallet[:8]}: {e}")
        
        except Exception as e:
            logger.error(f"Ошибка при проверке транзакций: {e}")
    
    def process_transactions_for_wallet(self, wallet_address, transactions, address_book):
        """Обработка транзакций для конкретного кошелька"""
        try:
            # Сохраняем только новые транзакции
            existing_tx_hashes = set()
            if wallet_address in self.last_transactions:
                existing_tx_hashes = {tx.get('hash') for tx in self.last_transactions[wallet_address]}
            
            new_transactions = []
            for tx in transactions:
                tx_hash = tx.get('hash')
                if tx_hash and tx_hash not in existing_tx_hashes:
                    new_transactions.append(tx)
            
            if new_transactions:
                # Сохраняем только новые транзакции (не перезаписываем старые)
                if wallet_address not in self.last_transactions:
                    self.last_transactions[wallet_address] = []
                
                # Добавляем только новые транзакции
                self.last_transactions[wallet_address] = new_transactions + self.last_transactions[wallet_address]
                
                # Ограничиваем количество сохраняемых транзакций
                self.last_transactions[wallet_address] = self.last_transactions[wallet_address][:50]
                
                self.save_last_transactions()
                logger.info(f"Сохранено {len(new_transactions)} новых транзакций для {wallet_address[:8]}...")
                
                # На первом запуске не отправляем уведомления о старых транзакциях
                if self.first_run:
                    logger.info(f"Первый запуск - игнорируем {len(new_transactions)} старых транзакций")
                    return  # Выходим из функции, не отправляем уведомления
                
                # Отправляем уведомления только о новых транзакциях
                self.send_transaction_notifications(wallet_address, new_transactions, address_book)
        
        except Exception as e:
            logger.error(f"Ошибка обработки транзакций для {wallet_address[:8]}: {e}")
    
    def send_transaction_notifications(self, wallet_address, transactions, address_book):
        """Отправка уведомлений о новых транзакциях через синхронный HTTP запрос"""
        try:
            if wallet_address not in self.wallets:
                return
            
            for chat_info in self.wallets[wallet_address]:
                chat_id = chat_info['chat_id']
                
                # Проверяем, включены ли уведомления для этого чата
                if self.get_notifications_status(int(chat_id)):
                    # Форматируем user-friendly адрес для отображения
                    wallet_info = address_book.get(wallet_address, {})
                    wallet_display = wallet_info.get('user_friendly', wallet_address)
                    
                    # Сокращаем адрес кошелька для заголовка
                    if len(wallet_display) > 10:
                        short_wallet = wallet_display[:6] + "..." + wallet_display[-4:]
                    else:
                        short_wallet = wallet_display
                    
                    message = f"🔔 *Новые транзакции по кошельку:*\n`{short_wallet}`\n\n"
                    
                    for tx in transactions[:5]:  # Ограничиваем 5 транзакциями
                        message += self.format_transaction_info(tx, address_book) + "\n\n" + "─" * 30 + "\n\n"
                    
                    # Отправляем сообщение через прямой HTTP запрос к Telegram API
                    self.send_telegram_message_sync(chat_id, message)
        
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")
    
    def send_telegram_message_sync(self, chat_id, message):
        """Синхронная отправка сообщения через Telegram API"""
        try:
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True
            }
            
            response = requests.post(TELEGRAM_API_URL, json=payload, timeout=30)
            
            if response.status_code == 200:
                logger.info(f"Уведомление отправлено в чат {chat_id}")
            else:
                logger.error(f"Ошибка отправки в чат {chat_id}: {response.status_code} - {response.text}")
        
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения в чат {chat_id}: {e}")

# Создаем экземпляр монитора
monitor = WalletMonitor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    logger.info(f"Команда /start от пользователя {update.effective_user.id}")
    welcome_text = """
🤖 *TON Wallet Monitor Bot*

*Доступные команды:*

👛 *Управление кошельками:*
/addwallet <адрес> - Добавить кошелек
/removewallet <адрес> - Удалить кошелек
/listwallets - Список кошельков

🔔 *Уведомления:*
/notifications_on - Включить уведомления
/notifications_off - Выключить уведомления

📊 *Информация:*
/lasttransactions - Последние транзакции
/help - Справка

*Пример использования:*
/addwallet EQjsjsjj....
/notifications_on
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /addwallet"""
    logger.info(f"Команда /addwallet от пользователя {update.effective_user.id}")
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    if not context.args:
        await update.message.reply_text(
            "❌ *Использование:* /addwallet <адрес_кошелька>\n\n"
            "*Пример:* /addwallet EQjsjsjj....",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    
    # Простая валидация адреса TON
    if not (wallet_address.startswith('EQ') or wallet_address.startswith('UQ')):
        await update.message.reply_text(
            "❌ *Неверный формат адреса!*\n\n"
            "Адрес TON кошелька должен начинаться с `EQ` или `UQ`",
            parse_mode='Markdown'
        )
        return
    
    try:
        if monitor.add_wallet(chat_id, wallet_address, chat_type):
            await update.message.reply_text(
                f"✅ *Кошелек добавлен!*\n\n"
                f"👛 *Адрес:* `{wallet_address}`\n"
                f"💬 *Чат:* {'Личные сообщения' if chat_type == 'private' else 'Групповой чат'}\n"
                f"🔔 *Уведомления:* {'Включены' if monitor.get_notifications_status(chat_id) else 'Выключены'}\n\n"
                f"Теперь бот будет отслеживать транзакции по этому кошельку.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"⚠️ *Кошелек уже добавлен!*\n\n"
                f"Кошелек `{wallet_address}` уже отслеживается в этом чате.",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Ошибка добавления кошелька: {e}")
        await update.message.reply_text("❌ Ошибка при добавлении кошелька")

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /removewallet"""
    logger.info(f"Команда /removewallet от пользователя {update.effective_user.id}")
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text(
            "❌ *Использование:* /removewallet <адрес_кошелька>\n\n"
            "*Пример:* /removewallet EQjsjsjj....\n"
            "📋 *Список кошельков:* /listwallets",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    
    try:
        if monitor.remove_wallet(chat_id, wallet_address):
            await update.message.reply_text(
                f"✅ *Кошелек удален!*\n\n"
                f"👛 *Адрес:* `{wallet_address}`\n"
                f"Теперь бот больше не отслеживает этот кошелек в этом чате.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"❌ *Кошелек не найден!*\n\n"
                f"Кошелек `{wallet_address}` не найден в списке отслеживаемых для этого чата.\n"
                f"📋 *Проверить список:* /listwallets",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Ошибка удаления кошелька: {e}")
        await update.message.reply_text("❌ Ошибка при удалении кошелька")

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /listwallets"""
    logger.info(f"Команда /listwallets от пользователя {update.effective_user.id}")
    chat_id = update.effective_chat.id
    
    try:
        message = monitor.format_wallet_list(chat_id)
        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка получения списка кошельков: {e}")
        await update.message.reply_text("❌ Ошибка при получении списка кошельков")

async def notifications_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /notifications_on"""
    logger.info(f"Команда /notifications_on от пользователя {update.effective_user.id}")
    chat_id = update.effective_chat.id
    
    try:
        monitor.set_notifications(chat_id, True)
        await update.message.reply_text(
            "🔔 *Уведомления включены!*\n\n"
            "Теперь вы будете получать уведомления о новых транзакциях.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка включения уведомлений: {e}")
        await update.message.reply_text("❌ Ошибка при включении уведомлений")

async def notifications_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /notifications_off"""
    logger.info(f"Команда /notifications_off от пользователя {update.effective_user.id}")
    chat_id = update.effective_chat.id
    
    try:
        monitor.set_notifications(chat_id, False)
        await update.message.reply_text(
            "🔕 *Уведомления выключены!*\n\n"
            "Вы больше не будете получать уведомления о новых транзакциях.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка выключения уведомлений: {e}")
        await update.message.reply_text("❌ Ошибка при выключении уведомлений")

async def last_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /lasttransactions"""
    logger.info(f"Команда /lasttransactions от пользователя {update.effective_user.id}")
    chat_id = update.effective_chat.id
    
    try:
        chat_wallets = monitor.get_chat_wallets(chat_id)
        if not chat_wallets:
            await update.message.reply_text(
                "📭 *Нет отслеживаемых кошельков*\n\n"
                "Добавьте кошельки командой /addwallet",
                parse_mode='Markdown'
            )
            return
        
        # Получаем актуальные данные для форматирования
        latest_transactions = {}
        for wallet in chat_wallets:
            if wallet in monitor.last_transactions:
                # Берем последние транзакции
                latest_tx = monitor.last_transactions[wallet][:3]
                if latest_tx:
                    latest_transactions[wallet] = latest_tx
        
        if not latest_transactions:
            await update.message.reply_text(
                "📭 *Транзакций пока нет*\n\nНовые транзакции появятся здесь после их обнаружения.",
                parse_mode='Markdown'
            )
            return
        
        message = "📊 *Последние транзакции:*\n\n"
        
        for wallet, tx_data in latest_transactions.items():
            message += f"👛 *Кошелек:* `{wallet}`\n\n"
            
            for tx in tx_data:
                # Для команды lasttransactions используем упрощенное форматирование
                try:
                    in_msg = tx.get('in_msg', {})
                    out_msgs = tx.get('out_msgs', [])
                    
                    if in_msg.get('source') and in_msg.get('destination'):
                        tx_type = "📥 Входящая"
                        amount = in_msg.get('value', '0')
                    elif out_msgs:
                        tx_type = "📤 Исходящая" 
                        amount = out_msgs[0].get('value', '0')
                    else:
                        tx_type = "🔁 Другая"
                        amount = '0'
                    
                    try:
                        amount_ton = int(amount) / 1e9
                        amount_str = f"{amount_ton:.4f} TON"
                    except:
                        amount_str = f"{amount} наноТОН"
                    
                    message += f"{tx_type} - {amount_str}\n"
                    message += f"⏰ {datetime.fromtimestamp(tx.get('now', 0)).strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                    
                except Exception as e:
                    logger.error(f"Ошибка форматирования транзакции: {e}")
                    message += "❌ Ошибка отображения транзакции\n\n"
            
            message += "─" * 30 + "\n\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка получения транзакций: {e}")
        await update.message.reply_text("❌ Ошибка при получении списка транзакций")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    logger.info(f"Команда /help от пользователя {update.effective_user.id}")
    help_text = """
📖 *Справка по командам TON Wallet Monitor Bot*

👛 *Управление кошельками:*
• `/addwallet <адрес>` - Добавить кошелек для отслеживания
• `/removewallet <адрес>` - Удалить кошелек из отслеживания  
• `/listwallets` - Показать все отслеживаемые кошельки

🔔 *Управление уведомлениями:*
• `/notifications_on` - Включить уведомления в этом чате
• `/notifications_off` - Выключить уведомления в этом чате

📊 *Просмотр информации:*
• `/lasttransactions` - Показать последние обнаруженные транзакции
• `/help` - Показать эту справку

*Примеры использования:*
1. Добавить кошелек:
   `/addwallet EQjsjsjj....`

2. Включить уведомления:
   `/notifications_on`

3. Посмотреть список кошельков:
   `/listwallets`

*Примечание:* Бот проверяет транзакции каждые 2 минуты
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

def background_monitor():
    """Фоновая задача для мониторинга транзакций"""
    logger.info("Фоновый мониторинг запущен")
    
    # Первый запуск - пропускаем отправку уведомлений
    monitor.first_run = True
    logger.info("Первый запуск - игнорируем старые транзакции")
    
    # Ждем 10 секунд перед первой проверкой
    time.sleep(10)
    
    while True:
        try:
            monitor.check_transactions_sync()
            
            # После первой проверки снимаем флаг первого запуска
            if monitor.first_run:
                monitor.first_run = False
                logger.info("Первый запуск завершен - теперь отправляем уведомления о новых транзакциях")
            
            time.sleep(120)  # 2 минуты
        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче: {e}")
            time.sleep(60)  # Ждем 1 минуту при ошибке

def main():
    """Основная функция"""
    # Запускаем фоновый мониторинг в отдельном потоке
    monitor_thread = threading.Thread(target=background_monitor, daemon=True)
    monitor_thread.start()
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики команд - ТОЛЬКО для команд начинающихся с /
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addwallet", add_wallet))
    application.add_handler(CommandHandler("removewallet", remove_wallet))
    application.add_handler(CommandHandler("listwallets", list_wallets))
    application.add_handler(CommandHandler("notifications_on", notifications_on))
    application.add_handler(CommandHandler("notifications_off", notifications_off))
    application.add_handler(CommandHandler("lasttransactions", last_transactions))
    application.add_handler(CommandHandler("help", help_command))
    
    # НЕ добавляем обработчик неизвестных команд - бот будет игнорировать чужие команды
    
    # Запускаем бота
    print("🤖 Бот запущен...")
    print("📊 Мониторинг транзакций активен")
    print("⏰ Проверка каждые 2 минуты")
    print("💫 Ожидаем команды...")
    print("🔧 Для теста отправьте /start боту в Telegram")
    print("🚫 Бот игнорирует команды других ботов")
    print("🆕 При запуске игнорируются старые транзакции")
    
    # Запускаем поллинг
    application.run_polling()

if __name__ == "__main__":
    main()
