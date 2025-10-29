import os
import logging
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from telegram.constants import ParseMode
from dotenv import load_dotenv

from database import DatabaseManager
from utils import format_file_size, is_allowed_file_type, sanitize_filename, create_file_info_text, download_file_from_url, is_valid_url, escape_markdown, AntiSpam

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
WAITING_FOR_NAME, WAITING_FOR_DESCRIPTION, WAITING_FOR_URL, WAITING_FOR_URL_NAME, WAITING_FOR_URL_DESCRIPTION, WAITING_FOR_BROADCAST, WAITING_FOR_ADMIN_COMMAND = range(7)

class ArchiveBot:
    def __init__(self):
        self.db = DatabaseManager()
        self.user_upload_data: Dict[int, Dict[str, Any]] = {}
        self.admin_id = int(os.getenv('ADMIN_USER_ID', 0))
        self.antispam = AntiSpam()
    
    async def check_antispam(self, update: Update, command: str = "general") -> bool:
        """Check antispam and send warning if needed"""
        user_id = update.effective_user.id
        
        # Skip antispam for admin
        if user_id == self.admin_id:
            return True
        
        # Periodic cleanup (fallback if JobQueue is not available)
        import random
        if random.randint(1, 100) == 1:  # 1% chance to cleanup on each request
            try:
                self.antispam.cleanup_old_data()
            except Exception as e:
                logger.error(f"Manual antispam cleanup failed: {e}")
        
        allowed, message = self.antispam.is_allowed(user_id, command)
        
        if not allowed:
            logger.warning(f"Antispam blocked user {user_id} for command {command}: {message}")
            
            # Send warning message
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            warning_text = (
                f"🚫 **Антиспам защита**\n\n"
                f"❌ {message}\n\n"
                f"💡 **Пожалуйста, используйте бот умеренно:**\n"
                f"• Не отправляйте команды слишком часто\n"
                f"• Не спамьте одной командой\n"
                f"• Подождите между запросами\n\n"
                f"⏰ Блокировка автоматически снимется через некоторое время."
            )
            
            try:
                if hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.answer(f"🚫 {message}", show_alert=True)
                else:
                    await update.message.reply_text(
                        warning_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
            except Exception as e:
                logger.error(f"Error sending antispam warning: {e}")
            
            return False
        
        return True
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        # Check antispam
        if not await self.check_antispam(update, "start"):
            return
        
        user = update.effective_user
        self.db.add_user(user.id, user.username, user.first_name, user.last_name)
        
        keyboard = [
            [InlineKeyboardButton("📤 Загрузить файл", callback_data="upload")],
            [InlineKeyboardButton("🔗 Скачать по ссылке", callback_data="url_download")],
            [InlineKeyboardButton("📦 Многочастная загрузка", callback_data="multipart_upload")],
            [InlineKeyboardButton("🔍 Поиск файлов", callback_data="search")],
            [InlineKeyboardButton("📋 Последние файлы", callback_data="recent")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton("👤 Мои файлы", callback_data="my_files")]
        ]
        
        # Add admin panel for admin user
        if user.id == self.admin_id:
            keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            "🗃️ **Добро пожаловать в Архив-бот!**\n\n"
            "Здесь вы можете:\n"
            "• Загружать файлы ЛЮБЫХ форматов (до 4 ГБ)\n"
            "• Отправлять фото, видео, аудио прямо в чат\n"
            "• Скачивать файлы по ссылке из любых источников\n"
            "• Загружать большие файлы по частям\n"
            "• Искать и скачивать файлы\n"
            "• Управлять своими файлами (удалять)\n"
            "• Просматривать статистику архива\n\n"
            "🔓 **Без ограничений на типы файлов!**\n"
            "🔒 **Защита от подделок - уникальные имена!**\n\n"
            "Выберите действие:"
        )
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard buttons"""
        query = update.callback_query
        logger.info(f"Button pressed: {query.data}")
        
        # Check antispam for button clicks
        if not await self.check_antispam(update, f"button_{query.data}"):
            return
        
        await query.answer()
        
        if query.data == "upload":
            await self.upload_prompt(query, context)
        elif query.data == "url_download":
            await self.url_download_prompt(query, context)
        elif query.data == "multipart_upload":
            await self.multipart_upload_prompt(query, context)
        elif query.data == "search":
            await self.search_prompt(query, context)
        elif query.data == "recent":
            await self.show_recent_files(query, context)
        elif query.data == "stats":
            await self.show_stats(query, context)
        elif query.data == "my_files":
            await self.show_user_files(query, context)
        elif query.data == "admin_panel":
            await self.show_admin_panel(query, context)
        elif query.data.startswith("download_"):
            try:
                file_id = int(query.data.split("_")[1])
                logger.info(f"Download request for file_id: {file_id}")
                await self.download_file(query, context, file_id)
            except Exception as e:
                logger.error(f"Error processing download button: {e}")
                await query.answer("❌ Ошибка при обработке запроса", show_alert=True)
        elif query.data.startswith("delete_"):
            try:
                file_id = int(query.data.split("_")[1])
                logger.info(f"Delete request for file_id: {file_id}")
                await self.confirm_delete(query, context, file_id)
            except Exception as e:
                logger.error(f"Error processing delete button: {e}")
                await query.answer("❌ Ошибка при обработке запроса", show_alert=True)
        elif query.data.startswith("confirm_delete_"):
            try:
                file_id = int(query.data.split("_")[2])
                logger.info(f"Confirmed delete for file_id: {file_id}")
                await self.delete_file(query, context, file_id)
            except Exception as e:
                logger.error(f"Error processing confirm delete: {e}")
                await query.answer("❌ Ошибка при обработке запроса", show_alert=True)
        elif query.data.startswith("cancel_delete_"):
            try:
                await self.show_user_files(query, context)
            except Exception as e:
                logger.error(f"Error canceling delete: {e}")
                await query.answer("❌ Ошибка при отмене", show_alert=True)
        elif query.data.startswith("user_files_page_"):
            try:
                page = int(query.data.split("_")[-1])
                await self.show_user_files(query, context, page)
            except Exception as e:
                logger.error(f"Error navigating user files: {e}")
                await query.answer("❌ Ошибка навигации", show_alert=True)
        elif query.data.startswith("recent_page_"):
            try:
                page = int(query.data.split("_")[-1])
                await self.show_recent_files(query, context, page)
            except Exception as e:
                logger.error(f"Error navigating recent files: {e}")
                await query.answer("❌ Ошибка навигации", show_alert=True)
        elif query.data.startswith("search_page_"):
            try:
                page = int(query.data.split("_")[-1])
                # Need to store search results in context for pagination
                await query.answer("Навигация по результатам поиска пока не поддерживается")
            except Exception as e:
                logger.error(f"Error navigating search results: {e}")
                await query.answer("❌ Ошибка навигации", show_alert=True)
        elif query.data == "noop":
            # Do nothing for counter button
            await query.answer()
        elif query.data == "back_to_menu":
            await self.back_to_menu(query, context)
        elif query.data == "admin_broadcast":
            await self.admin_broadcast_prompt(query, context)
        elif query.data == "admin_stats":
            await self.admin_detailed_stats(query, context)
        elif query.data == "admin_users":
            await self.admin_user_management(query, context)
        elif query.data == "admin_files":
            await self.admin_file_management(query, context)
        elif query.data == "admin_cleanup":
            await self.admin_cleanup_files(query, context)
        elif query.data.startswith("copy_name_"):
            try:
                file_id = int(query.data.split("_")[2])
                await self.copy_filename(query, context, file_id)
            except Exception as e:
                logger.error(f"Error copying filename: {e}")
                await query.answer("❌ Ошибка при копировании имени", show_alert=True)
        else:
            logger.warning(f"Unknown button data: {query.data}")
    
    async def upload_prompt(self, query, context):
        """Prompt user to upload a file"""
        text = (
            "📤 **Загрузка файла**\n\n"
            "Отправьте файл **ЛЮБОГО ФОРМАТА**, который хотите добавить в архив.\n"
            "Максимальный размер: 4 ГБ\n\n"
            "✅ **Поддерживаются ВСЕ форматы:**\n"
            "• 📸 Фото (отправьте прямо в чат)\n"
            "• 🎥 Видео (отправьте прямо в чат)\n"
            "• 🎵 Аудио и голосовые сообщения\n"
            "• 📄 Документы любых типов\n"
            "• 📦 Архивы, исполняемые файлы (.exe, .bat)\n"
            "• 🔧 Любые другие типы файлов\n\n"
            "💡 Для файлов больше 4 ГБ используйте многочастную загрузку"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle uploaded documents"""
        # Check antispam for file uploads
        if not await self.check_antispam(update, "upload_file"):
            return
        
        user_id = update.effective_user.id
        document = update.message.document
        
        # Check file type and size
        is_allowed, error_msg = is_allowed_file_type(document.file_name)
        if not is_allowed:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"❌ {error_msg}",
                reply_markup=reply_markup
            )
            return
        
        if document.file_size > 4 * 1024 * 1024 * 1024:  # 4 GB
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Файл слишком большой. Максимальный размер: 4 ГБ\n💡 Для больших файлов используйте многочастную загрузку",
                reply_markup=reply_markup
            )
            return
        
        # Store file info temporarily
        self.user_upload_data[user_id] = {
            'file_id': document.file_id,
            'original_name': document.file_name,
            'file_size': document.file_size,
            'mime_type': document.mime_type
        }
        
        await update.message.reply_text(
            f"📁 Файл получен: **{escape_markdown(document.file_name)}**\n"
            f"📊 Размер: {format_file_size(document.file_size)}\n\n"
            "Теперь введите название для файла в архиве:",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return WAITING_FOR_NAME
    
    async def handle_file_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file name input"""
        user_id = update.effective_user.id
        custom_name = sanitize_filename(update.message.text.strip())
        
        if not custom_name:
            await update.message.reply_text("❌ Название не может быть пустым. Попробуйте еще раз:")
            return WAITING_FOR_NAME
        
        # Check if filename is unique
        if not self.db.is_filename_unique(custom_name):
            suggested_name = self.db.suggest_unique_filename(custom_name)
            await update.message.reply_text(
                f"❌ **Файл с названием '{escape_markdown(custom_name)}' уже существует!**\n\n"
                f"🔒 **Защита от подделок активна**\n\n"
                f"💡 Предлагаемое название: `{escape_markdown(suggested_name)}`\n\n"
                "Введите другое уникальное название:",
                parse_mode=ParseMode.MARKDOWN
            )
            return WAITING_FOR_NAME
        
        self.user_upload_data[user_id]['custom_name'] = custom_name
        
        await update.message.reply_text(
            f"✅ Название: **{escape_markdown(custom_name)}**\n\n"
            "Теперь введите описание файла (или отправьте /skip чтобы пропустить):",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return WAITING_FOR_DESCRIPTION
    
    async def handle_file_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file description input"""
        user_id = update.effective_user.id
        description = update.message.text.strip() if update.message.text != "/skip" else ""
        
        # Save file to database
        file_data = self.user_upload_data[user_id]
        file_db_id = self.db.add_file(
            file_data['file_id'],
            file_data['original_name'],
            file_data['custom_name'],
            description,
            file_data['file_size'],
            file_data['mime_type'],
            user_id
        )
        
        # Clean up temporary data
        del self.user_upload_data[user_id]
        
        await update.message.reply_text(
            f"✅ **Файл успешно добавлен в архив!**\n\n"
            f"📁 Название: {escape_markdown(file_data['custom_name'])}\n"
            f"📝 Описание: {escape_markdown(description or 'Без описания')}\n"
            f"🆔 ID в архиве: {file_db_id}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ConversationHandler.END
    
    async def url_download_prompt(self, query, context):
        """Prompt user to enter URL for download"""
        text = (
            "🔗 **Скачивание по ссылке**\n\n"
            "Отправьте **ЛЮБУЮ** ссылку на файл - бот автоматически скачает его!\n"
            "Максимальный размер: 4 ГБ\n\n"
            "✅ **Поддерживаются:**\n"
            "• Google Drive, Dropbox, OneDrive\n"
            "• Yandex.Disk, GitHub, GitLab\n"
            "• Прямые ссылки на файлы\n"
            "• Ссылки с редиректами\n"
            "• Облачные хранилища\n\n"
            "💡 Просто вставьте любую ссылку!"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        context.user_data['waiting_for_url'] = True
    
    async def handle_url_download(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle URL download"""
        if not context.user_data.get('waiting_for_url'):
            return
        
        user_id = update.effective_user.id
        url = update.message.text.strip()
        
        # Validate URL
        if not is_valid_url(url):
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Неверный формат URL. Попробуйте еще раз:",
                reply_markup=reply_markup
            )
            return
        
        # Show downloading message
        downloading_msg = await update.message.reply_text("⏳ Скачиваю файл...")
        
        try:
            # Download file
            success, error_msg, file_content, filename, file_size = download_file_from_url(url)
            
            if not success:
                await downloading_msg.edit_text(f"❌ {error_msg}")
                return
            
            # Upload to Telegram to get file_id
            try:
                from io import BytesIO
                file_obj = BytesIO(file_content)
                file_obj.name = filename
                
                # Send file to get Telegram file_id
                sent_file = await update.message.reply_document(
                    document=file_obj,
                    filename=filename,
                    caption="📁 Файл загружен. Теперь добавим его в архив..."
                )
                
                telegram_file_id = sent_file.document.file_id
                
                # Store file info temporarily
                self.user_upload_data[user_id] = {
                    'file_id': telegram_file_id,
                    'original_name': filename,
                    'file_size': file_size,
                    'mime_type': sent_file.document.mime_type or 'application/octet-stream',
                    'from_url': True,
                    'source_url': url
                }
                
                await downloading_msg.delete()
                await update.message.reply_text(
                    f"✅ Файл успешно скачан: **{escape_markdown(filename)}**\n"
                    f"📊 Размер: {format_file_size(file_size)}\n\n"
                    "Теперь введите название для файла в архиве:",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                context.user_data['waiting_for_url'] = False
                return WAITING_FOR_URL_NAME
                
            except Exception as e:
                logger.error(f"Error uploading file to Telegram: {e}")
                await downloading_msg.edit_text("❌ Ошибка при загрузке файла в Telegram")
                return
                
        except Exception as e:
            logger.error(f"Error in URL download: {e}")
            await downloading_msg.edit_text("❌ Произошла ошибка при скачивании файла")
            return
    
    async def handle_url_file_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file name input for URL download"""
        user_id = update.effective_user.id
        custom_name = sanitize_filename(update.message.text.strip())
        
        if not custom_name:
            await update.message.reply_text("❌ Название не может быть пустым. Попробуйте еще раз:")
            return WAITING_FOR_URL_NAME
        
        # Check if filename is unique
        if not self.db.is_filename_unique(custom_name):
            suggested_name = self.db.suggest_unique_filename(custom_name)
            await update.message.reply_text(
                f"❌ **Файл с названием '{escape_markdown(custom_name)}' уже существует!**\n\n"
                f"🔒 **Защита от подделок активна**\n\n"
                f"💡 Предлагаемое название: `{escape_markdown(suggested_name)}`\n\n"
                "Введите другое уникальное название:",
                parse_mode=ParseMode.MARKDOWN
            )
            return WAITING_FOR_URL_NAME
        
        self.user_upload_data[user_id]['custom_name'] = custom_name
        
        await update.message.reply_text(
            f"✅ Название: **{escape_markdown(custom_name)}**\n\n"
            "Теперь введите описание файла (или отправьте /skip чтобы пропустить):",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return WAITING_FOR_URL_DESCRIPTION
    
    async def handle_url_file_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file description input for URL download"""
        user_id = update.effective_user.id
        description = update.message.text.strip() if update.message.text != "/skip" else ""
        
        # Save file to database
        file_data = self.user_upload_data[user_id]
        file_db_id = self.db.add_file(
            file_data['file_id'],
            file_data['original_name'],
            file_data['custom_name'],
            description,
            file_data['file_size'],
            file_data['mime_type'],
            user_id
        )
        
        # Clean up temporary data
        del self.user_upload_data[user_id]
        
        source_info = f"\n🔗 Источник: {escape_markdown(file_data.get('source_url', 'URL'))}" if file_data.get('from_url') else ""
        
        await update.message.reply_text(
            f"✅ **Файл успешно добавлен в архив!**\n\n"
            f"📁 Название: {escape_markdown(file_data['custom_name'])}\n"
            f"📝 Описание: {escape_markdown(description or 'Без описания')}\n"
            f"🆔 ID в архиве: {file_db_id}{source_info}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ConversationHandler.END
    
    async def multipart_upload_prompt(self, query, context):
        """Prompt user for multipart upload"""
        text = (
            "📦 **Многочастная загрузка**\n\n"
            "Для файлов больше 4 ГБ разделите их на части и загружайте по очереди.\n\n"
            "**Как использовать:**\n"
            "1. Разделите большой файл на части (например, с помощью 7-Zip или WinRAR)\n"
            "2. Загрузите первую часть\n"
            "3. Укажите общее количество частей\n"
            "4. Загрузите остальные части с тем же названием\n\n"
            "💡 **Совет:** Называйте части как `file.part1`, `file.part2` и т.д."
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        context.user_data['waiting_for_multipart'] = True
    
    async def search_prompt(self, query, context):
        """Prompt user to search files"""
        text = (
            "🔍 **Поиск файлов**\n\n"
            "Введите ключевые слова для поиска по названию или описанию файлов:"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        context.user_data['waiting_for_search'] = True
    
    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all text input based on context"""
        # Check antispam for text input
        if not await self.check_antispam(update, "text_input"):
            return
        
        # Handle URL download
        if context.user_data.get('waiting_for_url'):
            await self.handle_url_download(update, context)
            return
        
        # Handle search
        if context.user_data.get('waiting_for_search'):
            await self.handle_search(update, context)
            return
        
        # Handle multipart upload
        if context.user_data.get('waiting_for_multipart'):
            await self.handle_multipart_upload(update, context)
            return
        
        # Handle admin broadcast
        if context.user_data.get('waiting_for_broadcast'):
            await self.handle_broadcast_message(update, context)
            return
    
    async def handle_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle search query"""
        query_text = update.message.text.strip()
        if not query_text:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Поисковый запрос не может быть пустым",
                reply_markup=reply_markup
            )
            return
        
        results = self.db.search_files_grouped(query_text, limit=10)
        
        if not results:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🔍 По запросу **'{escape_markdown(query_text)}'** ничего не найдено",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_search'] = False
            return
        
        await self.show_file_results(update.message, results, f"🔍 Результаты поиска: '{escape_markdown(query_text)}'")
        context.user_data['waiting_for_search'] = False
    
    async def handle_multipart_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle multipart upload instructions"""
        await update.message.reply_text(
            "📦 **Многочастная загрузка активирована**\n\n"
            "Теперь отправьте первую часть файла как обычный документ.\n"
            "После загрузки я спрошу количество частей.",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['waiting_for_multipart'] = False
    
    async def show_recent_files(self, query, context, page=0):
        """Show recently uploaded files with pagination"""
        results = self.db.get_recent_files_grouped(limit=100)  # Get more files
        
        if not results:
            text = "📋 Архив пока пуст"
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup)
            return
        
        # Show one file per page
        total_files = len(results)
        if page >= total_files:
            page = 0
        elif page < 0:
            page = total_files - 1
            
        file_info = results[page]
        
        # Handle both old and new format
        if len(file_info) >= 11:  # New grouped format
            file_id, _, custom_name, description, file_size, _, download_count, username, first_name, is_multipart, total_parts, multipart_group_id = file_info[:12]
            multipart_info = f" (📦 {total_parts} частей)" if is_multipart else ""
        else:  # Old format
            file_id, _, custom_name, description, file_size, _, download_count, username, first_name = file_info
            multipart_info = ""
            description = description if len(file_info) > 3 else ""
        
        uploader = username or first_name or "Неизвестный"
        size_str = format_file_size(file_size)
        
        text = (
            f"📋 **Последние файлы** ({page + 1}/{total_files})\n\n"
            f"📁 **{escape_markdown(custom_name)}**{multipart_info}\n"
            f"📋 `{custom_name}`\n"
            f"📊 Размер: {size_str}\n"
        )
        
        if description:
            text += f"📝 {escape_markdown(description)}\n"
        
        text += f"👤 {escape_markdown(uploader)}\n"
        text += f"⬇️ Скачиваний: {download_count}"
        
        # Navigation and action buttons
        keyboard = []
        
        # Action buttons
        keyboard.append([
            InlineKeyboardButton("📥 Скачать", callback_data=f"download_{file_id}"),
            InlineKeyboardButton("📋 Копировать имя", callback_data=f"copy_name_{file_id}")
        ])
        
        # Navigation buttons
        nav_buttons = []
        if total_files > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"recent_page_{page-1}"))
            nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_files}", callback_data="noop"))
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"recent_page_{page+1}"))
            keyboard.append(nav_buttons)
        
        # Back button
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def show_user_files(self, query, context, page=0):
        """Show user's uploaded files with pagination"""
        user_id = query.from_user.id
        results = self.db.get_user_files(user_id, limit=100)  # Get all files
        
        if not results:
            text = "👤 У вас пока нет загруженных файлов"
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup)
            return
        
        # Show one file per page
        total_files = len(results)
        if page >= total_files:
            page = 0
        elif page < 0:
            page = total_files - 1
            
        file_info = results[page]
        file_id, _, custom_name, description, file_size, uploaded_at, download_count = file_info
        size_str = format_file_size(file_size)
        
        text = (
            f"👤 **Ваши файлы** ({page + 1}/{total_files})\n\n"
            f"📁 **{escape_markdown(custom_name)}**\n"
            f"📋 `{custom_name}`\n"
            f"📊 Размер: {size_str}\n"
        )
        
        if description:
            text += f"📝 {escape_markdown(description)}\n"
        
        text += f"📅 Загружен: {uploaded_at[:16]}\n"
        text += f"⬇️ Скачиваний: {download_count}"
        
        # Navigation and action buttons
        keyboard = []
        
        # File actions
        keyboard.append([
            InlineKeyboardButton("📥 Скачать", callback_data=f"download_{file_id}"),
            InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_{file_id}")
        ])
        keyboard.append([
            InlineKeyboardButton("📋 Копировать имя", callback_data=f"copy_name_{file_id}")
        ])
        
        # Navigation buttons
        nav_buttons = []
        if total_files > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"user_files_page_{page-1}"))
            nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_files}", callback_data="noop"))
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"user_files_page_{page+1}"))
            keyboard.append(nav_buttons)
        
        # Back button
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def show_stats(self, query, context):
        """Show archive statistics"""
        stats = self.db.get_stats()
        
        text = (
            "📊 **Статистика архива:**\n\n"
            f"📁 Всего файлов: {stats['total_files']}\n"
            f"👥 Пользователей: {stats['total_users']}\n"
            f"⬇️ Всего скачиваний: {stats['total_downloads']}\n"
            f"💾 Общий размер: {format_file_size(stats['total_size'])}"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def download_file(self, query, context, file_id):
        """Handle file download"""
        try:
            file_info = self.db.get_file_by_id(file_id)
            logger.info(f"Downloading file ID: {file_id}, file_info: {file_info}")
            
            if not file_info:
                await query.answer("❌ Файл не найден", show_alert=True)
                return
            
            # Send immediate feedback
            await query.answer("📥 Отправляю файл...")
            
            # Check if it's a multipart file
            if len(file_info) > 9 and file_info[9]:  # is_multipart field exists and is True
                multipart_group_id = file_info[12] if len(file_info) > 12 else None
                if multipart_group_id:
                    # Get all parts
                    parts = self.db.get_multipart_files(multipart_group_id)
                    if parts:
                        for part in parts:
                            try:
                                telegram_file_id = part[1]
                                part_text = f"📦 **Часть {part[9]} из {part[10]}**\n📁 {part[2]}"
                                await context.bot.send_document(
                                    chat_id=query.message.chat_id,
                                    document=telegram_file_id,
                                    caption=part_text,
                                    parse_mode=ParseMode.MARKDOWN
                                )
                            except Exception as e:
                                logger.error(f"Error sending part {part[9]}: {e}")
                                await context.bot.send_message(
                                    chat_id=query.message.chat_id,
                                    text=f"❌ Ошибка при отправке части {part[9]}: {str(e)}"
                                )
                        
                        # Increment download count for the main file
                        self.db.increment_download_count(file_id)
                        return
            
            # Regular single file download
            telegram_file_id = file_info[1]
            custom_name = file_info[2]
            description = file_info[3] if len(file_info) > 3 else ""
            
            # Create simple caption
            caption = f"📁 **{custom_name}**"
            if description:
                caption += f"\n📝 {description}"
            
            logger.info(f"Sending file with telegram_file_id: {telegram_file_id}")
            
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=telegram_file_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Increment download count
            self.db.increment_download_count(file_id)
            
        except Exception as e:
            logger.error(f"Error in download_file: {e}")
            await query.answer("❌ Ошибка при скачивании файла", show_alert=True)
            # Also send a message with error details
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Ошибка при скачивании файла: {str(e)}"
            )
    
    async def confirm_delete(self, query, context, file_id):
        """Show confirmation dialog for file deletion"""
        try:
            # Get file info to show in confirmation
            file_info = self.db.get_file_by_id(file_id)
            if not file_info:
                await query.answer("❌ Файл не найден", show_alert=True)
                return
            
            custom_name = file_info[2]
            
            text = (
                f"🗑️ **Подтверждение удаления**\n\n"
                f"Вы действительно хотите удалить файл:\n"
                f"📁 **{escape_markdown(custom_name)}**\n\n"
                f"⚠️ Это действие нельзя отменить!"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{file_id}"),
                    InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_delete_{file_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Error in confirm_delete: {e}")
            await query.answer("❌ Ошибка при подтверждении удаления", show_alert=True)
    
    async def delete_file(self, query, context, file_id):
        """Handle file deletion"""
        try:
            user_id = query.from_user.id
            
            # Try to delete the file
            success = self.db.delete_file(file_id, user_id)
            
            if success:
                await query.answer("✅ Файл удален!")
                # Refresh the current view
                await self.show_user_files(query, context)
            else:
                await query.answer("❌ Не удалось удалить файл. Возможно, он вам не принадлежит.", show_alert=True)
                
        except Exception as e:
            logger.error(f"Error in delete_file: {e}")
            await query.answer("❌ Ошибка при удалении файла", show_alert=True)
    
    async def copy_filename(self, query, context, file_id):
        """Handle filename copying"""
        try:
            # Get file info from database
            file_info = self.db.get_file_by_id(file_id)
            
            if not file_info:
                await query.answer("❌ Файл не найден", show_alert=True)
                return
            
            custom_name = file_info[2]  # custom_name is at index 2
            
            # Send filename in a copyable format
            text = (
                f"📋 **Имя файла для копирования:**\n\n"
                f"`{custom_name}`\n\n"
                f"💡 **Нажмите на имя файла выше, чтобы скопировать его**\n\n"
                f"📱 На мобильном: долгое нажатие → Копировать\n"
                f"💻 На компьютере: выделить → Ctrl+C"
            )
            
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send as new message for easy copying
            await query.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            await query.answer("📋 Имя файла отправлено для копирования!")
            
        except Exception as e:
            logger.error(f"Error in copy_filename: {e}")
            await query.answer("❌ Ошибка при копировании имени файла", show_alert=True)
    
    async def show_file_results(self, message, results, title, page=0):
        """Show file search results with pagination"""
        if not results:
            await message.reply_text(f"**{escape_markdown(title)}**\n\nНичего не найдено")
            return
            
        # Show one file per page
        total_files = len(results)
        if page >= total_files:
            page = 0
        elif page < 0:
            page = total_files - 1
            
        file_info = results[page]
        
        # Handle both old and new format
        if len(file_info) >= 11:  # New grouped format
            file_id, _, custom_name, description, file_size, _, download_count, username, first_name, is_multipart, total_parts, multipart_group_id = file_info[:12]
            multipart_info = f" (📦 {total_parts} частей)" if is_multipart else ""
        else:  # Old format
            file_id, _, custom_name, description, file_size, _, download_count, username, first_name = file_info
            multipart_info = ""
        
        uploader = username or first_name or "Неизвестный"
        size_str = format_file_size(file_size)
        
        text = (
            f"**{escape_markdown(title)}** ({page + 1}/{total_files})\n\n"
            f"📁 **{escape_markdown(custom_name)}**{multipart_info}\n"
            f"📋 `{custom_name}`\n"
            f"📊 Размер: {size_str}\n"
        )
        
        if description:
            text += f"📝 {escape_markdown(description)}\n"
        
        text += f"👤 {escape_markdown(uploader)}\n⬇️ Скачиваний: {download_count}"
        
        # Navigation and action buttons
        keyboard = []
        
        # Action buttons
        keyboard.append([
            InlineKeyboardButton("📥 Скачать", callback_data=f"download_{file_id}"),
            InlineKeyboardButton("📋 Копировать имя", callback_data=f"copy_name_{file_id}")
        ])
        
        # Navigation buttons
        nav_buttons = []
        if total_files > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"search_page_{page-1}"))
            nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_files}", callback_data="noop"))
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"search_page_{page+1}"))
            keyboard.append(nav_buttons)
        
        # Back button
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def back_to_menu(self, query, context):
        """Return to main menu"""
        keyboard = [
            [InlineKeyboardButton("📤 Загрузить файл", callback_data="upload")],
            [InlineKeyboardButton("🔗 Скачать по ссылке", callback_data="url_download")],
            [InlineKeyboardButton("📦 Многочастная загрузка", callback_data="multipart_upload")],
            [InlineKeyboardButton("🔍 Поиск файлов", callback_data="search")],
            [InlineKeyboardButton("📋 Последние файлы", callback_data="recent")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton("👤 Мои файлы", callback_data="my_files")]
        ]
        
        # Add admin panel for admin user
        if query.from_user.id == self.admin_id:
            keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            "🗃️ **Архив-бот**\n\n"
            "Выберите действие:"
        )
        
        await query.edit_message_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Clear any waiting states
        context.user_data.clear()
    
    async def test_download(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Test download functionality"""
        # Check antispam
        if not await self.check_antispam(update, "test"):
            return
        
        # Get the last uploaded file
        results = self.db.get_recent_files_grouped(limit=1)
        if not results:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Нет файлов для тестирования",
                reply_markup=reply_markup
            )
            return
        
        file_info = results[0]
        file_id = file_info[0]
        custom_name = file_info[2]
        
        keyboard = [
            [InlineKeyboardButton(f"📥 Скачать {custom_name}", callback_data=f"download_{file_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🧪 **Тест скачивания**\n\nПоследний файл: {escape_markdown(custom_name)}\nID: {file_id}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel current operation"""
        user_id = update.effective_user.id
        if user_id in self.user_upload_data:
            del self.user_upload_data[user_id]
        
        await update.message.reply_text("❌ Операция отменена")
        return ConversationHandler.END
    
    # ============ ADMIN FUNCTIONS ============
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id == self.admin_id
    
    async def show_admin_panel(self, query, context):
        """Show admin panel"""
        if not self.is_admin(query.from_user.id):
            await query.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        text = (
            "⚙️ **Админ-панель**\n\n"
            "🔧 **Доступные функции:**\n"
            "• Рассылка сообщений всем пользователям\n"
            "• Детальная статистика системы\n"
            "• Управление пользователями\n"
            "• Управление файлами\n"
            "• Очистка старых файлов\n\n"
            "Выберите действие:"
        )
        
        keyboard = [
            [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📊 Детальная статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_users")],
            [InlineKeyboardButton("📁 Управление файлами", callback_data="admin_files")],
            [InlineKeyboardButton("🧹 Очистка файлов", callback_data="admin_cleanup")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def admin_broadcast_prompt(self, query, context):
        """Prompt admin for broadcast message"""
        if not self.is_admin(query.from_user.id):
            await query.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        text = (
            "📢 **Рассылка сообщения**\n\n"
            "Введите текст сообщения, которое будет отправлено всем пользователям бота:\n\n"
            "💡 **Поддерживается Markdown разметка**"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        context.user_data['waiting_for_broadcast'] = True
    
    async def admin_detailed_stats(self, query, context):
        """Show detailed admin statistics"""
        if not self.is_admin(query.from_user.id):
            await query.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        stats = self.db.get_admin_stats()
        
        text = (
            "📊 **Детальная статистика**\n\n"
            f"👥 **Пользователи:** {stats.get('total_users', 0)}\n"
            f"📁 **Всего файлов:** {stats.get('total_files', 0)}\n"
            f"💾 **Общий размер:** {format_file_size(stats.get('total_size', 0))}\n"
            f"⬇️ **Всего скачиваний:** {stats.get('total_downloads', 0)}\n"
            f"🔗 **Файлов из URL:** {stats.get('url_files', 0)}\n"
            f"📦 **Многочастных файлов:** {stats.get('multipart_files', 0)}\n\n"
            f"📈 **Активность за сегодня:**\n"
            f"• Новых пользователей: {stats.get('users_today', 0)}\n"
            f"• Загружено файлов: {stats.get('files_today', 0)}\n"
            f"• Скачиваний: {stats.get('downloads_today', 0)}"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def admin_user_management(self, query, context):
        """Show user management options"""
        if not self.is_admin(query.from_user.id):
            await query.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        users = self.db.get_top_users(limit=10)
        
        text = "👥 **Управление пользователями**\n\n📈 **Топ пользователей по загрузкам:**\n\n"
        
        for i, user in enumerate(users, 1):
            username = user[1] or user[2] or "Неизвестный"
            files_count = user[3]
            text += f"{i}. {escape_markdown(username)} - {files_count} файлов\n"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def admin_file_management(self, query, context):
        """Show file management options"""
        if not self.is_admin(query.from_user.id):
            await query.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        large_files = self.db.get_largest_files(limit=10)
        
        text = "📁 **Управление файлами**\n\n📊 **Самые большие файлы:**\n\n"
        
        for i, file_info in enumerate(large_files, 1):
            filename = file_info[1]
            size = format_file_size(file_info[2])
            downloads = file_info[3]
            text += f"{i}. {escape_markdown(filename)} - {size} ({downloads} скачиваний)\n"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def admin_cleanup_files(self, query, context):
        """Show file cleanup options"""
        if not self.is_admin(query.from_user.id):
            await query.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        text = (
            "🧹 **Очистка файлов**\n\n"
            "⚠️ **Внимание!** Эта функция удалит файлы без возможности восстановления.\n\n"
            "🗂️ **Доступные опции очистки:**\n"
            "• Файлы старше 30 дней без скачиваний\n"
            "• Файлы с 0 скачиваний старше 7 дней\n"
            "• Файлы больше 1 ГБ старше 14 дней\n\n"
            "💡 Функция в разработке..."
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle uploaded photos"""
        # Check antispam for file uploads
        if not await self.check_antispam(update, "upload_photo"):
            return
        
        user_id = update.effective_user.id
        photo = update.message.photo[-1]  # Get the largest photo
        
        # Create a document-like object for consistency
        class PhotoDocument:
            def __init__(self, photo):
                self.file_id = photo.file_id
                self.file_size = photo.file_size
                self.file_name = f"photo_{photo.file_unique_id}.jpg"
                self.mime_type = "image/jpeg"
        
        # Replace the photo with document-like object and process
        update.message.document = PhotoDocument(photo)
        await self.handle_document(update, context)
    
    async def handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle uploaded videos"""
        # Check antispam for file uploads
        if not await self.check_antispam(update, "upload_video"):
            return
        
        user_id = update.effective_user.id
        video = update.message.video
        
        # Create a document-like object for consistency
        class VideoDocument:
            def __init__(self, video):
                self.file_id = video.file_id
                self.file_size = video.file_size
                self.file_name = video.file_name or f"video_{video.file_unique_id}.mp4"
                self.mime_type = video.mime_type or "video/mp4"
        
        # Replace the video with document-like object and process
        update.message.document = VideoDocument(video)
        await self.handle_document(update, context)
    
    async def handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle uploaded audio files"""
        # Check antispam for file uploads
        if not await self.check_antispam(update, "upload_audio"):
            return
        
        user_id = update.effective_user.id
        audio = update.message.audio
        
        # Create a document-like object for consistency
        class AudioDocument:
            def __init__(self, audio):
                self.file_id = audio.file_id
                self.file_size = audio.file_size
                self.file_name = audio.file_name or f"audio_{audio.file_unique_id}.mp3"
                self.mime_type = audio.mime_type or "audio/mpeg"
        
        # Replace the audio with document-like object and process
        update.message.document = AudioDocument(audio)
        await self.handle_document(update, context)
    
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice messages"""
        # Check antispam for file uploads
        if not await self.check_antispam(update, "upload_voice"):
            return
        
        user_id = update.effective_user.id
        voice = update.message.voice
        
        # Create a document-like object for consistency
        class VoiceDocument:
            def __init__(self, voice):
                self.file_id = voice.file_id
                self.file_size = voice.file_size
                self.file_name = f"voice_{voice.file_unique_id}.ogg"
                self.mime_type = voice.mime_type or "audio/ogg"
        
        # Replace the voice with document-like object and process
        update.message.document = VoiceDocument(voice)
        await self.handle_document(update, context)
    
    async def handle_video_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle video notes (круглые видео)"""
        # Check antispam for file uploads
        if not await self.check_antispam(update, "upload_video_note"):
            return
        
        user_id = update.effective_user.id
        video_note = update.message.video_note
        
        # Create a document-like object for consistency
        class VideoNoteDocument:
            def __init__(self, video_note):
                self.file_id = video_note.file_id
                self.file_size = video_note.file_size
                self.file_name = f"video_note_{video_note.file_unique_id}.mp4"
                self.mime_type = "video/mp4"
        
        # Replace the video note with document-like object and process
        update.message.document = VideoNoteDocument(video_note)
        await self.handle_document(update, context)
    
    async def handle_broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle broadcast message from admin"""
        if not context.user_data.get('waiting_for_broadcast'):
            return
        
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        broadcast_text = update.message.text.strip()
        if not broadcast_text:
            await update.message.reply_text("❌ Сообщение не может быть пустым")
            return
        
        # Get all users
        users = self.db.get_all_users()
        
        sent_count = 0
        failed_count = 0
        
        status_msg = await update.message.reply_text("📤 Начинаю рассылку...")
        
        for user_id, username, first_name, last_name in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 **Сообщение от администрации:**\n\n{broadcast_text}",
                    parse_mode=ParseMode.MARKDOWN
                )
                sent_count += 1
                
                # Update status every 10 messages
                if sent_count % 10 == 0:
                    await status_msg.edit_text(f"📤 Отправлено: {sent_count}/{len(users)}")
                
            except Exception as e:
                logger.error(f"Failed to send broadcast to {user_id}: {e}")
                failed_count += 1
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.1)
        
        final_text = (
            f"✅ **Рассылка завершена!**\n\n"
            f"📤 Отправлено: {sent_count}\n"
            f"❌ Не удалось отправить: {failed_count}\n"
            f"👥 Всего пользователей: {len(users)}"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await status_msg.edit_text(
            final_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        context.user_data['waiting_for_broadcast'] = False
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command handler"""
        # Check antispam (but admin is exempt)
        if not await self.check_antispam(update, "admin"):
            return
        
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ У вас нет прав администратора")
            return
        
        # Create fake query for admin panel
        class FakeQuery:
            def __init__(self, user, message):
                self.from_user = user
                self.message = message
            
            async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                await self.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        
        fake_query = FakeQuery(update.effective_user, update.message)
        await self.show_admin_panel(fake_query, context)
    
    async def cleanup_antispam_data(self, context: ContextTypes.DEFAULT_TYPE):
        """Periodic cleanup of antispam data"""
        try:
            self.antispam.cleanup_old_data()
            logger.info("Antispam data cleanup completed")
        except Exception as e:
            logger.error(f"Error during antispam cleanup: {e}")
    
    def run(self):
        """Run the bot"""
        token = os.getenv('BOT_TOKEN')
        if not token:
            raise ValueError("BOT_TOKEN not found in environment variables")
        
        # Create application
        application = Application.builder().token(token).build()
        
        # Add conversation handler for file upload
        upload_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Document.ALL, self.handle_document)],
            states={
                WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_file_name)],
                WAITING_FOR_DESCRIPTION: [MessageHandler(filters.TEXT, self.handle_file_description)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
        )
        
        # Add conversation handler for URL download
        url_download_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_input)],
            states={
                WAITING_FOR_URL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_url_file_name)],
                WAITING_FOR_URL_DESCRIPTION: [MessageHandler(filters.TEXT, self.handle_url_file_description)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
        )
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("admin", self.admin_command))
        application.add_handler(CommandHandler("test", self.test_download))
        application.add_handler(CallbackQueryHandler(self.button_handler))
        application.add_handler(upload_handler)
        application.add_handler(url_download_handler)
        
        # Add media handlers
        application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        application.add_handler(MessageHandler(filters.VIDEO, self.handle_video))
        application.add_handler(MessageHandler(filters.AUDIO, self.handle_audio))
        application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        application.add_handler(MessageHandler(filters.VIDEO_NOTE, self.handle_video_note))
        
        # Add periodic antispam cleanup job (every 30 minutes) if JobQueue is available
        try:
            if application.job_queue:
                application.job_queue.run_repeating(
                    self.cleanup_antispam_data,
                    interval=1800,  # 30 minutes
                    first=300       # Start after 5 minutes
                )
                logger.info("Antispam cleanup job scheduled")
            else:
                logger.warning("JobQueue not available - antispam cleanup will be manual only")
        except Exception as e:
            logger.warning(f"Could not set up cleanup job: {e}")
        
        # Run the bot
        logger.info("Starting Archive Bot with Anti-Spam protection...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    bot = ArchiveBot()
    bot.run()
