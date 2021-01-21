from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters,
                              ConversationHandler,CallbackQueryHandler, PicklePersistence)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import flexpoolapi
import logging
from time import sleep

#LOGGING
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)

# SECURITY CONSTANTS
BOT_TOKEN = 'YOUR TOKEN FROM BOTFATHER'

TIME_BETWEEN_POOLS = 120

# Telegram BOT states
SET_WALLET_ADDR, SET_MIN_HASHRATE_THRESHOLD, NOTIFY_ON_NEW_BALANCE, IDLE = range(4)

# Telegram BOT job callbacks
def job_hashrate(context):
    chat_data = context.job.context
    bot = context.bot
    
    effective_hashrate, _ = chat_data['miner'].current_hashrate()
    min_hashrate_threshold = chat_data['min_hashrate_threshold']
    if effective_hashrate/1e6 < min_hashrate_threshold:
        bot.send_message(chat_id=chat_data['chat_id'],
                         text=("Current effective hashrate is bellow threshold \n"
                               f"Current effective hashrate: {effective_hashrate/1e6:.0f}MH/s.\n"
                               f"Threshold is fixed to {min_hashrate_threshold}MH/s\n"
                               "Send /snooze to stop this alert for 30min"))

def job_balance(context):
    chat_data = context.job.context
    bot = context.bot

    if chat_data['monitor_balance'] :
        balance_new = chat_data['miner'].balance()
        balance_old = chat_data['balance_old']
        if chat_data['balance_old'] != balance_new:
            bot.send_message(chat_id=chat_data['chat_id'],
                         text=(f"Balanced has changed: {(balance_new-balance_old)/1e18:+.4f}\n"
                               f"old balance: {balance_old/1e18:.4f}ETH\n"
                               f"new balance: {balance_new/1e18:.4f}ETH"))
            chat_data['balance_old'] = balance_new

# Telegram BOT states and fallbacks callbacks
def start(update, context):
    chat_data = context.chat_data
    chat_data['chat_id'] = str(update.message.chat_id)

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
    except Exception as e:
        update.message.reply_text(str(e))
        return ConversationHandler.END
    if chat_data['min_hashrate_threshold'] > 0:
        job_queue.run_repeating(job_hashrate, interval=TIME_BETWEEN_POOLS, first=0, context=chat_data, name=chat_data['chat_id']+'hashrate')

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
        job_queue.run_repeating(job_balance, interval=TIME_BETWEEN_POOLS, first=0, context=chat_data, name=chat_data['chat_id']+'balance')
    else:
        chat_data['monitor_balance'] = False
    return welcome_idle(update, context)


def remove_job_if_exists(name, context):
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


def cancel(update, context):
    chat_data = context.chat_data
    for job_type in ('hashrate','balance'):
        remove_job_if_exists(chat_data['chat_id']+job_type, context)
    update.message.reply_text("Job Stopped! You will stop receiving alerts. Send /start to create a new job")
    return ConversationHandler.END

def welcome_idle(update, context):
    chat_data = context.chat_data
    bot = context.bot

    n_jobs = int(chat_data['min_hashrate_threshold']>0) + int(chat_data['monitor_balance'])
    monitor_balance = chat_data['monitor_balance']
    min_hashrate_threshold = chat_data['min_hashrate_threshold']
    bot.send_message(chat_id=chat_data['chat_id'], text = (f"{n_jobs} job(s) running. \n"
                                                            f"Balance monitoring: {monitor_balance}\n"
                                                            f"Min hashrate threshold: {min_hashrate_threshold:.0f} MH/S\n"
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
        stats_str += f"{field} : {getattr(stats,field):.0f}\n"
    bot.send_message(chat_id=chat_data['chat_id'], text=stats_str)
    return IDLE

def get_balance(update, context):
    chat_data = context.chat_data
    bot = context.bot
    bot.send_message(chat_id=chat_data['chat_id'], text=f"Current balance: {chat_data['miner'].balance()/1e18:.4f}")

def snooze(update, context):
    chat_data = context.chat_data
    job_queue = context.job_queue
    bot = context.bot
    
    if not remove_job_if_exists(chat_data['chat_id']+ 'hashrate', context):
        bot.send_message(chat_id=chat_data['chat_id'], text="Nothing to snooze")
    else:
        bot.send_message(chat_id=chat_data['chat_id'], text="Hashrate alerts snoozed for 30min")
        job_queue.run_repeating(job_hashrate, interval=TIME_BETWEEN_POOLS, first=2, context=chat_data, name=chat_data['chat_id']+'hashrate')
    return IDLE

def error_handler(update, context) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    return IDLE

def restore_jobs(job_queue,chat_data_dict):
    for _, chat_data in chat_data_dict.items():
        if chat_data['min_hashrate_threshold'] > 0:
            job_queue.run_repeating(job_hashrate, interval=TIME_BETWEEN_POOLS, first=0, context=chat_data, name=chat_data['chat_id']+'hashrate')
            logger.info(msg=f"{chat_data['chat_id']} job hashrate restarted")

        if chat_data['monitor_balance'] == True:
            job_queue.run_repeating(job_balance, interval=TIME_BETWEEN_POOLS, first=0, context=chat_data, name=chat_data['chat_id']+'balance')
            logger.info(msg=f"{chat_data['chat_id']} job balance restarted")
def main():
    pp = PicklePersistence(filename='flexpoolbot')
    updater = Updater(token=BOT_TOKEN, persistence=pp, use_context=True)
    dispatcher = updater.dispatcher

    handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={

            SET_WALLET_ADDR: [MessageHandler(Filters.text, set_wallet_address)],

            SET_MIN_HASHRATE_THRESHOLD: [MessageHandler(Filters.text, set_min_hashrate_threshold)],

            NOTIFY_ON_NEW_BALANCE: [CallbackQueryHandler(notify_on_new_balance)],

            IDLE: [CommandHandler('stats', stats), CommandHandler('status', welcome_idle),
                 CommandHandler('balance', get_balance), CommandHandler('snooze',snooze)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        name='ConversationHandler',
        persistent=True 
    )
    dispatcher.add_handler(handler)
    dispatcher.add_error_handler(error_handler)
    restore_jobs(updater.job_queue, pp.get_chat_data())
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()