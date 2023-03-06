import datetime
import html
import logging
import traceback

import pandas as pd
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    ParseMode,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ChatAction,
)
from telegram.ext import CallbackQueryHandler
from telegram.ext import Updater, CallbackContext, CommandHandler, ConversationHandler, MessageHandler, Filters

from probablefutures.probablefutures import ProbableFutures
from probablefuturesbot.tools import read_config, run_request, read_csv, write_csv

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

outdir = "logs"
logs_name = "logs"

config = read_config(outdir)

df_columns = ["group", "timestamp", "lat", "lon", "address", "warming_scenario", "map_id", "hashed_user"]

df = read_csv(outdir, logs_name, df_columns)

developer_chat_id = config["developer_chat_id"]
bot_token = config["bot_token"]
pf_user = config["username"]
pf_password = config["password"]

(START, LOCATION, WARMING_SCENARIO, MAP) = range(4)

location_info = dict()
address = dict()
selected_warming_scenario = dict()

pf = ProbableFutures(user=pf_user, password=pf_password)
pf.connect()

response = run_request("GET", "https://probable-futures.github.io/docs/assets/js/search-data.json")
maps = dict()
for r in response["19"]["content"].split("| . |")[1:]:
    maps[int(r.split(" | ")[0].strip())] = r.split(" | ")[1].strip()


def start(update: Update, context: CallbackContext) -> int:
    context.bot.send_message(
        update.message.chat.id,
        "Hi there! I’m Probable Futures Bot.\n"
        "Send me a location and I'll send you back some info from https://probablefutures.org/.\n"
        "For logging purposes, the input information (location, warming scenario and map type) is saved, "
        "but can not be traced to a user, as the chat_id is hashed (anonymised).\n"
        "If you find issues or have any questions, please contact probablefuturesbot@jakubwaller.eu\n"
        "Feel free to also check out the code at: https://github.com/jakubwaller/probable-futures-bot",
    )

    return START


def probable_future(update: Update, context: CallbackContext) -> int:
    chat_id = update.message.chat.id
    location_keyboard = KeyboardButton(text="send_location", request_location=True)
    custom_keyboard = [[location_keyboard]]
    reply_markup = ReplyKeyboardMarkup(custom_keyboard)
    context.bot.send_message(
        chat_id=chat_id,
        text="You can either share your location or send any address you like.",
        reply_markup=reply_markup,
    )

    return LOCATION


def location(update: Update, context: CallbackContext) -> int:
    chat_id = update.message.chat.id
    location_info[chat_id] = None
    address[chat_id] = None

    if update.message.location:
        latitude = update.message.location.latitude
        longitude = update.message.location.longitude
        location_info[chat_id] = (latitude, longitude)
    else:
        address[chat_id] = update.message.text.strip()

    keyboard = [InlineKeyboardButton(d, callback_data=d) for d in ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]]

    chunk_size = 3
    chunks = [keyboard[x : x + chunk_size] for x in range(0, len(keyboard), chunk_size)]

    reply_markup = InlineKeyboardMarkup(chunks)

    context.bot.send_message(chat_id, "Select a warming scenario.", reply_markup=reply_markup)

    return WARMING_SCENARIO


def warming_scenario(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat.id

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    query.answer()

    selected_warming_scenario[chat_id] = query.data

    query.edit_message_text(text=f"Selected warming scenario: {query.data}")

    keyboard = [InlineKeyboardButton(name, callback_data=map_id) for map_id, name in maps.items()]

    chunk_size = 1
    chunks = [keyboard[x : x + chunk_size] for x in range(0, len(keyboard), chunk_size)]

    reply_markup = InlineKeyboardMarkup(chunks)

    context.bot.send_message(chat_id, "Select a map.", reply_markup=reply_markup)

    return MAP


def map(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat.id
    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    query.answer()

    selected_map_id = int(query.data)

    query.edit_message_text(text=f"Selected map: {maps[selected_map_id]}")

    if location_info[chat_id]:
        input_fields = {
            "lon": str(location_info[chat_id][1]),
            "lat": str(location_info[chat_id][0]),
            "warmingScenario": selected_warming_scenario[chat_id],
            "datasetId": selected_map_id,
        }
    else:
        input_fields = {
            "address": address[chat_id],
            "warmingScenario": selected_warming_scenario[chat_id],
            "datasetId": selected_map_id,
        }

    try:
        if "group" in update.message.chat.type:
            is_group = True
        else:
            is_group = False
    except Exception as e:
        logger.error(e)
        is_group = False

    global df
    log_entry = [
        is_group,
        datetime.datetime.now(),
        location_info[chat_id][0],
        location_info[chat_id][1],
        address[chat_id],
        selected_warming_scenario[chat_id],
        selected_map_id,
        hash(chat_id),
    ]
    context.bot.send_message(developer_chat_id, str(log_entry))
    df = pd.concat([df, pd.DataFrame([log_entry], columns=df_columns)])
    write_csv(df, outdir, logs_name)

    output_fields = ["highValue", "lowValue", "midValue", "unit", "warmingScenario", "latitude", "longitude"]
    response = pf.request(input_fields=input_fields, output_fields=output_fields)
    response_json = response.json()

    try:
        low_value = response_json["data"]["getDatasetStatistics"]["datasetStatisticsResponses"][0]["lowValue"]
        mid_value = response_json["data"]["getDatasetStatistics"]["datasetStatisticsResponses"][0]["midValue"]
        high_value = response_json["data"]["getDatasetStatistics"]["datasetStatisticsResponses"][0]["highValue"]
        unit = response_json["data"]["getDatasetStatistics"]["datasetStatisticsResponses"][0]["unit"]

        try:
            lat = response_json["data"]["getDatasetStatistics"]["datasetStatisticsResponses"][0]["latitude"]
            lon = response_json["data"]["getDatasetStatistics"]["datasetStatisticsResponses"][0]["longitude"]
            response_location = f"""Location (lat, lon): ({lat}, {lon}):\n"""
        except Exception:
            response_location = f"""Address: {address[chat_id]}:\n"""

        response_message = (
            response_location,
            f"5th Percentile: {low_value} {unit}\n",
            f"Average: {mid_value} {unit}\n",
            f"95th Percentile: {high_value} {unit}",
        )
        context.bot.send_message(chat_id, response_message)
    except Exception as e:
        if "Invalid lon param." in str(response_json):
            response_message = "Invalid address/location!"
            context.bot.send_message(chat_id, response_message)
        else:
            response_message = response_json
            context.bot.send_message(chat_id, response_message)
            raise e

    return START


def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels the current operation."""

    context.bot.send_message(update.message.chat.id, "Current operation cancelled.")

    return START


def error_handler(update: object, context: CallbackContext):
    """Log the error and send a telegram message to notify the developer."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    message = f"An exception was raised while handling an update\n" f"<pre>{html.escape(tb_string)}"

    message = message[:1000] + "</pre>"

    context.bot.send_message(chat_id=developer_chat_id, text=message, parse_mode=ParseMode.HTML)


def main() -> None:
    """Setup and run the bot."""
    # Create the Updater and pass it your bot's token.
    updater = Updater(bot_token)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), CommandHandler("probable_future", probable_future)],
        states={
            START: [CommandHandler("probable_future", probable_future), MessageHandler(~Filters.command, location)],
            LOCATION: [MessageHandler(~Filters.command, location)],
            WARMING_SCENARIO: [CallbackQueryHandler(warming_scenario)],
            MAP: [CallbackQueryHandler(map)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    updater.dispatcher.add_handler(conv_handler)

    updater.dispatcher.add_error_handler(error_handler)

    # Start the Bot
    updater.start_polling()

    # Run the bot until the user presses Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT
    updater.idle()


if __name__ == "__main__":
    main()
