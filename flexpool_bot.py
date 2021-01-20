from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters,
                              ConversationHandler,CallbackQueryHandler)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import flexpoolapi


# SECURITY CONSTANTS

BOT_TOKEN = 'YOUR TOKEN FROM BOTFATHER'
ADMIN_USERNAME = 'FILL YOUR USERNAME'

# To notify the users before a bot update/restart
chats_id_list = list()

TIME_BETWEEN_POOLS = 120

# Telegram BOT states
SET_WALLET_ADDR, SET_MIN_HASHRATE_THRESHOLD, NOTIFY_ON_NEW_BALANCE, IDLE = range(4)

# Telegram BOT job callbacks

def job_hashrate(context):
    chat_data = context.job.context
    bot = context.bot
    
    effective_hashrate, _ = chat_data['miner'].current_hashrate()
    min_hashrate_threshold = chat_data['min_hashrate_threshold']
    effective_hashrate_mh = effective_hashrate/1e6
    if effective_hashrate_mh < min_hashrate_threshold:
        bot.send_message(chat_id=chat_data['chat_id'],
                         text=("Current effective hashrate is bellow threshold \n"
                               f"Current effective hashrate: {effective_hashrate_mh}. Threshold is fixed to {min_hashrate_threshold}"))

def job_balance(context):
    chat_data = context.job.context
    bot = context.bot

    if chat_data['monitor_balance'] :
        balance_new = chat_data['miner'].balance()
        balance_old = chat_data['balance_old']

        balance_new_eth = balance_new/1e18
        balance_old_eth = balance_old/1e18

        if chat_data['balance_old'] != balance_new:

            bot.send_message(chat_id=chat_data['chat_id'],
                         text=("Balanced has changed \n"
                               f"old balance: {balance_old}({balance_old_eth}ETH) --> new balance: {balance_new}({balance_new_eth}ETH) "))
            chat_data['balance_old'] = balance_new

# Telegram BOT states and fallbacks callbacks

def start(update, context):
    chat_data = context.chat_data
    chat_data['chat_id'] = update.message.chat_id
    chat_data['jobs']= []

    global chats_id_list
    chats_id_list.append(update.message.chat_id)
    
    update.message.reply_text("Enter your eth wallet address")
    return SET_WALLET_ADDR


def set_wallet_address(update, context):
    chat_data = context.chat_data
    try:
        chat_data['miner'] = flexpoolapi.miner(update.message.text)
    except Exception as e:
        update.message.reply_text(str(e))
        return ConversationHandler.END
    update.message.reply_text("Please enter the minimum hashrate threshold in MH/s, you will be notified if you go bellow \nSet to 0 if you don't want to be alerted")
    return SET_MIN_HASHRATE_THRESHOLD

def set_min_hashrate_threshold(update, context):
    chat_data = context.chat_data
    job_queue = context.job_queue
    try:
        chat_data['min_hashrate_threshold'] = float(update.message.text)
        if chat_data['min_hashrate_threshold'] > 0:
            job = job_queue.run_repeating(job_hashrate, interval=TIME_BETWEEN_POOLS, first=0, context=chat_data)
            chat_data['jobs'].append(job)
    except Exception as e:
        update.message.reply_text(str(e))
        return ConversationHandler.END

    keyboard = [ InlineKeyboardButton("Yes", callback_data='yes'), InlineKeyboardButton("No", callback_data='no')]
    update.message.reply_text("Do you want to be notified when your balance is updated?", reply_markup=InlineKeyboardMarkup.from_row(keyboard))

    return NOTIFY_ON_NEW_BALANCE

def notify_on_new_balance(update, context):
    chat_data = context.chat_data
    job_queue = context.job_queue
    query = update.callback_query
    query.answer()
    if query.data == 'yes':
        chat_data['monitor_balance'] = True 
        chat_data['balance_old'] = chat_data['miner'].balance()
        job = job_queue.run_repeating(job_balance, interval=TIME_BETWEEN_POOLS, first=0, context=chat_data)
        chat_data['jobs'].append(job)

    else:
        chat_data['monitor_balance'] = False
        
    return welcome_idle(update, context)


def cancel(update, context):
    chat_data = context.chat_data
    
    for job in chat_data['jobs']:
        job.schedule_removal()
    update.message.reply_text("Job Stopped! You will stop receiving alerts. Send /start to create a new job")
    return ConversationHandler.END


def notify_users(update, context):
    bot = context.bot

    if update.message.from_user.username != ADMIN_USERNAME:
        update.message.reply_text("unauthorized username!")
        return
    for chat_id in chats_id_list:
        bot.send_message(chat_id=chat_id, text="The BOT is about to restart, you'll need to restart a new job")

def welcome_idle(update, context):
    chat_data = context.chat_data
    bot = context.bot

    n_jobs = len(chat_data['jobs'])
    monitor_balance = chat_data['monitor_balance']
    min_hashrate_threshold = chat_data['min_hashrate_threshold']
    bot.send_message(chat_id=chat_data['chat_id'], text = (f"{n_jobs} job(s) running. \n"
                                                            f"Balance monitoring: {monitor_balance}\n"
                                                            f"Min hashrate threshold: {min_hashrate_threshold} MH/S\n"
                                                            "Send /stats to see statistics of your miner\n"
                                                            "Send /status to see the status of your jobs\n"
                                                            "Send /cancel to stop your jobs"))
    return IDLE

def stats(update, context):
    chat_data = context.chat_data
    bot = context.bot

    stats_str = ''
    stats = chat_data['miner'].stats()
    for field in [
        'current_effective_hashrate','current_reported_hashrate',
        'average_effective_hashrate','average_reported_hashrate',
        'valid_shares', 'stale_shares', 'invalid_shares' ] :
        stats_str += field + ': ' + str(getattr(stats,field)) + '\n'
    bot.send_message(chat_id=chat_data['chat_id'], text=stats_str)
    return IDLE


updater = Updater(token=BOT_TOKEN)

dispatcher = updater.dispatcher

handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={

        SET_WALLET_ADDR: [MessageHandler(Filters.text, set_wallet_address)],

        SET_MIN_HASHRATE_THRESHOLD: [MessageHandler(Filters.text, set_min_hashrate_threshold)],

        NOTIFY_ON_NEW_BALANCE: [CallbackQueryHandler(notify_on_new_balance)],

        IDLE: [CommandHandler('stats', stats), CommandHandler('status', welcome_idle)],
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)
admin_handler = CommandHandler('admin', notify_users)
dispatcher.add_handler(handler)
dispatcher.add_handler(admin_handler)
updater.start_polling()
updater.idle()


