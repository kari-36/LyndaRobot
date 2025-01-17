from io import BytesIO
from typing import List
import uuid
import re
import json
import time
import csv
import os

from telegram.error import BadRequest, TelegramError, Unauthorized
from telegram import ParseMode, Update, MessageEntity, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import run_async, CommandHandler, CallbackQueryHandler, CallbackContext
from telegram.utils.helpers import mention_html, mention_markdown

from lynda import dispatcher, OWNER_ID, SUDO_USERS, WHITELIST_USERS, SARDEGNA_USERS, GBAN_LOGS, LOGGER
from lynda.modules.helper_funcs.chat_status import is_user_admin
from lynda.modules.helper_funcs.extraction import extract_user, extract_unt_fedban, extract_user_fban
from lynda.modules.helper_funcs.string_handling import markdown_parser
from lynda.modules.disable import DisableAbleCommandHandler

import lynda.modules.sql.feds_sql as sql
from lynda.modules.helper_funcs.alternate import send_message

# Hello bot owner, I spended for feds many hours of my life,
# Please don't remove this if you still respect MrYacha and peaktogoo and AyraHikari too
# Federation by MrYacha 2018-2019
# Federation rework by Mizukito Akito 2019
# Federation update v2 by Ayra Hikari 2019
# Time spended on feds = 10h by #MrYacha
# Time spended on reworking on the whole feds = 22+ hours by @peaktogoo
# Time spended on updating version to v2 = 26+ hours by @AyraHikari
# Total spended for making this features is 68+ hours
# LOGGER.info("Original federation module by MrYacha, reworked by Mizukito Akito (@peaktogoo) on Telegram.")

FBAN_ERRORS = {
    "User is an administrator of the chat",
    "Chat not found",
    "Not enough rights to restrict/unrestrict chat member",
    "User_not_participant",
    "Peer_id_invalid",
    "Group chat was deactivated",
    "Need to be inviter of a user to kick it from a basic group",
    "Chat_admin_required",
    "Only the creator of a basic group can kick group administrators",
    "Channel_private",
    "Not in the chat",
    "Have no rights to send a message"
}

UNFBAN_ERRORS = {
    "User is an administrator of the chat",
    "Chat not found",
    "Not enough rights to restrict/unrestrict chat member",
    "User_not_participant",
    "Method is available for supergroup and channel chats only",
    "Not in the chat",
    "Channel_private",
    "Chat_admin_required",
    "Have no rights to send a message"
}


@run_async
def new_fed(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type != "private":
        message.reply_text(
            "Federations can only be created by privately messaging me.")
        return
    if len(message.text) == 1:
        send_message(message,
                    "Please write the name of the federation!")
        return
    fednam = message.text.split(None, 1)[1]
    if fednam != '':
        fed_id = str(uuid.uuid4())
        fed_name = fednam
        LOGGER.info(fed_id)
        x = sql.new_fed(user.id, fed_name, fed_id)
        if not x:
            message.reply_text(
                "Can't federate! Please contact @LyndaEagleSupport if the problem persist.")
            return

        message.reply_text(
            "*You have succeeded in creating a new federation!*"
            "\nName: `{}`"
            "\nID: `{}`"
            "\n\nUse the command below to join the federation:"
            "\n`/joinfed {}`".format(
                fed_name,
                fed_id,
                fed_id),
            parse_mode=ParseMode.MARKDOWN)
        try:
            context.bot.send_message(GBAN_LOGS,
                            "New Federation: <b>{}</b>\nID: <pre>{}</pre>".format(fed_name,
                                                                                fed_id),
                            parse_mode=ParseMode.HTML)
        except BaseException:
            LOGGER.warning("Cannot send a message to GBAN_LOGS")
    else:
        message.reply_text(
            "Please write down the name of the federation")


@run_async
def del_fed(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type != "private":
        message.reply_text(
            "Federations can only be deleted by privately messaging me.")
        return
    if args:
        is_fed_id = args[0]
        getinfo = sql.get_fed_info(is_fed_id)
        if not getinfo:
            message.reply_text(
                "This federation does not exist.")
            return
        if int(getinfo['owner']) == int(user.id) or int(user.id) == OWNER_ID:
            fed_id = is_fed_id
        else:
            message.reply_text(
                "Only federation owners can do this!")
            return
    else:
        message.reply_text("What should I delete?")
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        message.reply_text(
            "Only federation owners can do this!")
        return

    message.reply_text(
        "You sure you want to delete your federation? This cannot be reverted, you will lose your entire ban list, and '{}' will be permanently lost.".format(
            getinfo['fname']), reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="⚠️ Delete Federation ⚠️", callback_data="rmfed_{}".format(fed_id))], [
                InlineKeyboardButton(
                    text="Cancel", callback_data="rmfed_cancel")]]))


@run_async
def fed_chat(update: Update, _):
    chat = update.effective_chat
    fed_id = sql.get_fed_id(chat.id)
    message = update.effective_message
    user_id = message.from_user.id
    if not is_user_admin(update.effective_chat, user_id):
        message.reply_text(
            "You must be an admin to execute this command")
        return

    if not fed_id:
        message.reply_text(
            "This group is not in any federation!")
        return

    chat = update.effective_chat
    info = sql.get_fed_info(fed_id)

    text = "This group is part of the following federation:"
    text += "\n{} (ID: <code>{}</code>)".format(info['fname'], fed_id)

    message.reply_text(text, parse_mode=ParseMode.HTML)


@run_async
def join_fed(update: Update, context: CallbackContext):
    chat = update.effective_chat
    args = context.args
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return
    administrators = chat.get_administrators()
    fed_id = sql.get_fed_id(chat.id)

    if user.id not in SUDO_USERS:
        for admin in administrators:
            status = admin.status
            if status == "creator" and str(admin.user.id) != str(user.id):
                message.reply_text(
                    "Only group creators can use this command!")
                return
    if fed_id:
        message.reply_text("You cannot join two federations from one chat")
        return

    if len(args) >= 1:
        getfed = sql.search_fed_by_id(args[0])
        if not getfed:
            message.reply_text("Please enter a valid federation ID")
            return

        x = sql.chat_join_fed(args[0], chat.title, chat.id)
        if not x:
            message.reply_text(
                "Failed to join federation! Please contact @LyndaEagleSupport should this problem persist!")
            return

        get_fedlog = sql.get_fed_log(args[0])
        if get_fedlog and eval(get_fedlog):
            context.bot.send_message(
                get_fedlog,
                "Chat *{}* has joined the federation *{}*".format(
                    chat.title,
                    getfed['fname']),
                parse_mode="markdown")

        message.reply_text(
            "This group has joined the federation: {}!".format(
                getfed['fname']))


@run_async
def leave_fed(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our PM!")
        return

    fed_id = sql.get_fed_id(chat.id)
    fed_info = sql.get_fed_info(fed_id)

    # administrators = chat.get_administrators().status
    getuser = context.bot.get_chat_member(chat.id, user.id).status
    if getuser in 'creator' or user.id in SUDO_USERS:
        if sql.chat_leave_fed(chat.id):
            get_fedlog = sql.get_fed_log(fed_id)
            if get_fedlog and eval(get_fedlog):
                context.bot.send_message(
                    get_fedlog, "Chat *{}* has left the federation *{}*".format(
                        chat.title, fed_info['fname']), parse_mode="markdown")
            send_message(
                message,
                "This group has left the federation {}!".format(
                    fed_info['fname']))
        else:
            message.reply_text(
                "How can you leave a federation that you never joined?!")
    else:
        message.reply_text(
            "Only group creators can use this command!")


@run_async
def user_join_fed(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                     "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)

    if is_user_fed_owner(fed_id, user.id) or user.id in SUDO_USERS:
        args = context.args
        user_id = extract_user(message, args)
        if user_id:
            user = context.bot.get_chat(user_id)
        elif not message.reply_to_message and not args:
            user = message.from_user
        elif (
            not message.reply_to_message
            and len(args) >= 1
            and not args[0].startswith("@")
            and not args[0].isdigit()
            and not message.parse_entities([MessageEntity.TEXT_MENTION])
        ):
            message.reply_text("I cannot extract user from this message")
            return
        else:
            LOGGER.warning('error')
        getuser = sql.search_user_in_fed(fed_id, user_id)
        fed_id = sql.get_fed_id(chat.id)
        info = sql.get_fed_info(fed_id)
        get_owner = eval(info['fusers'])['owner']
        get_owner = context.bot.get_chat(get_owner).id
        if user_id == get_owner:
            message.reply_text(
                "You do know that the user is the federation owner, right? RIGHT?")
            return
        if getuser:
            message.reply_text(
                "I cannot promote users who are already federation admins! Can remove them if you want!")
            return
        if user_id == context.bot.id:
            message.reply_text(
                "I already am a federation admin in all federations!")
            return
        res = sql.user_join_fed(fed_id, user_id)
        if res:
            message.reply_text("Successfully Promoted!")
        else:
            message.reply_text("Failed to promote!")
    else:
        message.reply_text(
            "Only federation owners can do this!")


@run_async
def user_demote_fed(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)

    if is_user_fed_owner(fed_id, user.id):
        args = context.args
        user_id = extract_user(message, args)
        if user_id:
            user = context.bot.get_chat(user_id)

        elif not message.reply_to_message and not args:
            user = message.from_user

        elif (
            not message.reply_to_message
            and len(args) >= 1
            and not args[0].startswith("@")
            and not args[0].isdigit()
            and not message.parse_entities([MessageEntity.TEXT_MENTION])
        ):
            message.reply_text("I cannot extract user from this message")
            return
        else:
            LOGGER.warning('error')

        if user_id == context.bot.id:
            message.reply_text(
                "The thing you are trying to demote me from will fail to work without me! Just saying.")
            return

        if sql.search_user_in_fed(fed_id, user_id) is False:
            message.reply_text(
                "I cannot demote people who are not federation admins!")
            return

        res = sql.user_demote_fed(fed_id, user_id)
        if res:
            message.reply_text("Demoted from a Fed Admin!")
        else:
            message.reply_text("Demotion failed!")
    else:
        message.reply_text(
            "Only federation owners can do this!")
        return


@run_async
def fed_info(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if args:
        fed_id = args[0]
    else:
        fed_id = sql.get_fed_id(chat.id)
        if not fed_id:
            send_message(
                message,
                "This group is not in any federation!")
            return
    info = sql.get_fed_info(fed_id)
    if is_user_fed_admin(fed_id, user.id) is False:
        message.reply_text(
            "Only a federation admin can do this!")
        return

    owner = context.bot.get_chat(info['owner'])
    try:
        owner_name = owner.first_name + " " + owner.last_name
    except BaseException as e:
        print(e)
        owner_name = owner.first_name
    FEDADMIN = sql.all_fed_users(fed_id)
    FEDADMIN.append(int(owner.id))
    TotalAdminFed = len(FEDADMIN)

    user = update.effective_user
    chat = update.effective_chat
    info = sql.get_fed_info(fed_id)

    text = "<b>ℹ️ Federation Information:</b>"
    text += "\nFedID: <code>{}</code>".format(fed_id)
    text += "\nName: {}".format(info['fname'])
    text += "\nCreator: {}".format(mention_html(owner.id, owner_name))
    text += "\nAll Admins: <code>{}</code>".format(TotalAdminFed)
    getfban = sql.get_all_fban_users(fed_id)
    text += "\nTotal banned users: <code>{}</code>".format(len(getfban))
    getfchat = sql.all_fed_chats(fed_id)
    text += "\nNumber of groups in this federation: <code>{}</code>".format(
        len(getfchat))

    message.reply_text(text, parse_mode=ParseMode.HTML)


@run_async
def fed_admin(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)

    if not fed_id:
        message.reply_text(
            "This group is not in any federation!")
        return

    if is_user_fed_admin(fed_id, user.id) is False:
        message.reply_text(
            "Only federation admins can do this!")
        return

    user = update.effective_user
    chat = update.effective_chat
    info = sql.get_fed_info(fed_id)

    text = "<b>Federation Admin {}:</b>\n\n".format(info['fname'])
    text += "👑 Owner:\n"
    owner = context.bot.get_chat(info['owner'])
    try:
        owner_name = owner.first_name + " " + owner.last_name
    except BaseException:
        owner_name = owner.first_name
    text += " - {}\n".format(mention_html(owner.id, owner_name))

    members = sql.all_fed_members(fed_id)
    if len(members) == 0:
        text += "\n🔱 There are no admins in this federation"
    else:
        text += "\n🔱 Admin:\n"
        for x in members:
            user = context.bot.get_chat(x)
            text += " - {}\n".format(mention_html(user.id, user.first_name))

    message.reply_text(text, parse_mode=ParseMode.HTML)


@run_async
def fed_ban(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)

    if not fed_id:
        message.reply_text(
            "This group is not a part of any federation!")
        return

    info = sql.get_fed_info(fed_id)
    getfednotif = sql.user_feds_report(info['owner'])

    if is_user_fed_admin(fed_id, user.id) is False:
        message.reply_text(
            "Only federation admins can do this!")
        return
    user_id, reason = extract_unt_fedban(message, args)

    fban, _, _ = sql.get_fban_user(fed_id, user_id)

    if not user_id:
        message.reply_text("You don't seem to be referring to a user")
        return

    if user_id == context.bot.id:
        message.reply_text(
            "What is funnier than kicking the group creator? Self sacrifice.")
        return

    if is_user_fed_owner(fed_id, user_id):
        message.reply_text("Why did you try the federation fban?")
        return

    if is_user_fed_admin(fed_id, user_id):
        message.reply_text("He is a federation admin, I can't fban him.")
        return

    if user_id == OWNER_ID:
        message.reply_text("Diaster level God cannot be fed banned!")
        return

    if int(user_id) in SUDO_USERS:
        message.reply_text("Dragons cannot be fed banned!")
        return

    if int(user_id) in SARDEGNA_USERS:
        message.reply_text("Tigers cannot be fed banned!")
        return

    if int(user_id) in WHITELIST_USERS:
        message.reply_text("Wolves cannot be fed banned!")
        return

    try:
        user_chat = context.bot.get_chat(user_id)
        isvalid = True
        fban_user_id = user_chat.id
        fban_user_name = user_chat.first_name
        fban_user_lname = user_chat.last_name
        fban_user_uname = user_chat.username
    except BadRequest as excp:
        if not str(user_id).isdigit():
            send_message(message, excp.message)
            return
        elif len(str(user_id)) != 9:
            send_message(message, "That's so not a user!")
            return
        isvalid = False
        fban_user_id = int(user_id)
        fban_user_name = "user({})".format(user_id)
        fban_user_lname = None
        fban_user_uname = None

    if isvalid and user_chat.type != 'private':
        send_message(message, "That's so not a user!")
        return

    if isvalid:
        user_target = mention_html(fban_user_id, fban_user_name)
    else:
        user_target = fban_user_name

    if fban:
        fed_name = info['fname']
        if reason == "":
            reason = "No reason given."

        temp = sql.un_fban_user(fed_id, fban_user_id)
        if not temp:
            message.reply_text("Failed to update the reason for fedban!")
            return
        x = sql.fban_user(
            fed_id,
            fban_user_id,
            fban_user_name,
            fban_user_lname,
            fban_user_uname,
            reason,
            int(time.time()))
        if not x:
            message.reply_text(
                "Failed to ban from the federation! If this problem continues, contact @LyndaEagleSupport.")
            return

        fed_chats = sql.all_fed_chats(fed_id)
        # Will send to current chat
        context.bot.send_message(
            chat.id,
            "<b>FedBan reason updated</b>"
            "\n<b>Federation:</b> {}"
            "\n<b>Federation Admin:</b> {}"
            "\n<b>User:</b> {}"
            "\n<b>User ID:</b> <code>{}</code>"
            "\n<b>Reason:</b> {}".format(
                fed_name,
                mention_html(
                    user.id,
                    user.first_name),
                    user_target,
                    fban_user_id,
                    reason),
            parse_mode="HTML")
        # Send message to owner if fednotif is enabled
        if getfednotif:
            context.bot.send_message(
                info['owner'],
                "<b>FedBan reason updated</b>"
                "\n<b>Federation:</b> {}"
                "\n<b>Federation Admin:</b> {}"
                "\n<b>User:</b> {}"
                "\n<b>User ID:</b> <code>{}</code>"
                "\n<b>Reason:</b> {}".format(fed_name,
                                            mention_html(user.id,
                                            user.first_name),
                                            user_target,
                                            fban_user_id,
                                            reason),
                parse_mode="HTML")
        # If fedlog is set, then send message, except fedlog is current chat
        get_fedlog = sql.get_fed_log(fed_id)
        if get_fedlog and int(get_fedlog) != int(chat.id):
            context.bot.send_message(get_fedlog,
                            "<b>FedBan reason updated</b>"
                            "\n<b>Federation:</b> {}"
                            "\n<b>Federation Admin:</b> {}"
                            "\n<b>User:</b> {}"
                            "\n<b>User ID:</b> <code>{}</code>"
                            "\n<b>Reason:</b> {}".format(fed_name,
                                                        mention_html(user.id,
                                                                    user.first_name),
                                                        user_target,
                                                        fban_user_id,
                                                        reason),
                            parse_mode="HTML")
        for fedschat in fed_chats:
            try:
                # Do not spam all fed chats
                """
                bot.send_message(chat, "<b>FedBan reason updated</b>" \
                                        "\n<b>Federation:</b> {}" \
                                        "\n<b>Federation Admin:</b> {}" \
                                        "\n<b>User:</b> {}" \
                                        "\n<b>User ID:</b> <code>{}</code>" \
                                        "\n<b>Reason:</b> {}".format(fed_name, mention_html(user.id, user.first_name), user_target, fban_user_id, reason), parse_mode="HTML")
                """
                context.bot.kick_chat_member(fedschat, fban_user_id)
            except BadRequest as excp:
                if excp.message in FBAN_ERRORS:
                    try:
                        dispatcher.bot.getChat(fedschat)
                    except Unauthorized:
                        sql.chat_leave_fed(fedschat)
                        LOGGER.info(
                            "Chat {} has leave fed {} because I was kicked".format(
                                fedschat, info['fname']))
                        continue
                elif excp.message == "User_id_invalid":
                    break
                else:
                    LOGGER.warning(
                        "Could not fban on {} because: {}".format(
                            chat, excp.message))
            except TelegramError:
                pass
        # Also do not spam all fed admins
        """
        send_to_list(bot, FEDADMIN,
                "<b>FedBan reason updated</b>" \
                            "\n<b>Federation:</b> {}" \
                            "\n<b>Federation Admin:</b> {}" \
                            "\n<b>User:</b> {}" \
                            "\n<b>User ID:</b> <code>{}</code>" \
                            "\n<b>Reason:</b> {}".format(fed_name, mention_html(user.id, user.first_name), user_target, fban_user_id, reason),
                            html=True)
        """

        # Fban for fed subscriber
        subscriber = list(sql.get_subscriber(fed_id))
        if len(subscriber) != 0:
            for fedsid in subscriber:
                all_fedschat = sql.all_fed_chats(fedsid)
                for fedschat in all_fedschat:
                    try:
                        context.bot.kick_chat_member(fedschat, fban_user_id)
                    except BadRequest as excp:
                        if excp.message in FBAN_ERRORS:
                            try:
                                dispatcher.bot.getChat(fedschat)
                            except Unauthorized:
                                targetfed_id = sql.get_fed_id(fedschat)
                                sql.unsubs_fed(fed_id, targetfed_id)
                                LOGGER.info(
                                    "Chat {} has unsub fed {} because I was kicked".format(
                                        fedschat, info['fname']))
                                continue
                        elif excp.message == "User_id_invalid":
                            break
                        else:
                            LOGGER.warning(
                                "Unable to fban on {} because: {}".format(
                                    fedschat, excp.message))
                    except TelegramError:
                        pass
        # send_message(message, "Fedban Reason has been updated.")
        return

    fed_name = info['fname']

    starting = "Starting a federation ban for {} in the Federation <b>{}</b>.".format(
        user_target, fed_name)
    message.reply_text(starting, parse_mode=ParseMode.HTML)

    if reason == "":
        reason = "No reason given."

    x = sql.fban_user(
        fed_id,
        fban_user_id,
        fban_user_name,
        fban_user_lname,
        fban_user_uname,
        reason,
        int(time.time()))
    if not x:
        message.reply_text(
            "Failed to ban from the federation! If this problem continues, contact @LyndaEagleSupport.")
        return

    fed_chats = sql.all_fed_chats(fed_id)
    # Will send to current chat
    context.bot.send_message(chat.id,
                    "<b>FedBan reason updated</b>"
                    "\n<b>Federation:</b> {}"
                    "\n<b>Federation Admin:</b> {}"
                    "\n<b>User:</b> {}"
                    "\n<b>User ID:</b> <code>{}</code>"
                    "\n<b>Reason:</b> {}".format(fed_name,
                                                mention_html(user.id,
                                                            user.first_name),
                                                user_target,
                                                fban_user_id,
                                                reason),
                    parse_mode="HTML")
    # Send message to owner if fednotif is enabled
    if getfednotif:
        context.bot.send_message(info['owner'],
                        "<b>FedBan reason updated</b>"
                        "\n<b>Federation:</b> {}"
                        "\n<b>Federation Admin:</b> {}"
                        "\n<b>User:</b> {}"
                        "\n<b>User ID:</b> <code>{}</code>"
                        "\n<b>Reason:</b> {}".format(fed_name,
                                                    mention_html(user.id,
                                                                user.first_name),
                                                    user_target,
                                                    fban_user_id,
                                                    reason),
                        parse_mode="HTML")
    # If fedlog is set, then send message, except fedlog is current chat
    get_fedlog = sql.get_fed_log(fed_id)
    if get_fedlog and int(get_fedlog) != int(chat.id):
        context.bot.send_message(get_fedlog,
                        "<b>FedBan reason updated</b>"
                        "\n<b>Federation:</b> {}"
                        "\n<b>Federation Admin:</b> {}"
                        "\n<b>User:</b> {}"
                        "\n<b>User ID:</b> <code>{}</code>"
                        "\n<b>Reason:</b> {}".format(fed_name,
                                                    mention_html(user.id,
                                                                user.first_name),
                                                    user_target,
                                                    fban_user_id,
                                                    reason),
                        parse_mode="HTML")
    chats_in_fed = 0
    for fedschat in fed_chats:
        chats_in_fed += 1
        try:
            # Do not spamming all fed chats
            """
            context.bot.send_message(chat, "<b>FedBan reason updated</b>" \
                                            "\n<b>Federation:</b> {}" \
                                            "\n<b>Federation Admin:</b> {}" \
                                            "\n<b>User:</b> {}" \
                                            "\n<b>User ID:</b> <code>{}</code>" \
                                            "\n<b>Reason:</b> {}".format(fed_name, mention_html(user.id, user.first_name), user_target, fban_user_id, reason), parse_mode="HTML")
            """
            context.bot.kick_chat_member(fedschat, fban_user_id)
        except BadRequest as excp:
            if excp.message in FBAN_ERRORS:
                pass
            elif excp.message == "User_id_invalid":
                break
            else:
                LOGGER.warning(
                    "Could not fban on {} because: {}".format(
                        chat, excp.message))
        except TelegramError:
            pass

        # Also do not spamming all fed admins
        """
		send_to_list(context.bot, FEDADMIN,
				 "<b>FedBan reason updated</b>" \
							 "\n<b>Federation:</b> {}" \
							 "\n<b>Federation Admin:</b> {}" \
							 "\n<b>User:</b> {}" \
							 "\n<b>User ID:</b> <code>{}</code>" \
							 "\n<b>Reason:</b> {}".format(fed_name, mention_html(user.id, user.first_name), user_target, fban_user_id, reason),
							html=True)
		"""

        # Fban for fed subscriber
        subscriber = list(sql.get_subscriber(fed_id))
        if len(subscriber) != 0:
            for fedsid in subscriber:
                all_fedschat = sql.all_fed_chats(fedsid)
                for fedschat in all_fedschat:
                    try:
                        context.bot.kick_chat_member(fedschat, fban_user_id)
                    except BadRequest as excp:
                        if excp.message in FBAN_ERRORS:
                            try:
                                dispatcher.bot.getChat(fedschat)
                            except Unauthorized:
                                targetfed_id = sql.get_fed_id(fedschat)
                                sql.unsubs_fed(fed_id, targetfed_id)
                                LOGGER.info(
                                    "Chat {} has unsub fed {} because I was kicked".format(
                                        fedschat, info['fname']))
                                continue
                        elif excp.message == "User_id_invalid":
                            break
                        else:
                            LOGGER.warning(
                                "Unable to fban on {} because: {}".format(
                                    fedschat, excp.message))
                    except TelegramError:
                        pass
    if chats_in_fed == 0:
        send_message(message, "Fedban affected 0 chats. ")
    elif chats_in_fed > 0:
        send_message(message,
                     "Fedban affected {} chats. ".format(chats_in_fed))


@run_async
def unfban(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)

    if not fed_id:
        message.reply_text(
            "This group is not a part of any federation!")
        return

    info = sql.get_fed_info(fed_id)
    getfednotif = sql.user_feds_report(info['owner'])

    if is_user_fed_admin(fed_id, user.id) is False:
        message.reply_text(
            "Only federation admins can do this!")
        return

    user_id = extract_user_fban(message, args)
    if not user_id:
        message.reply_text("You do not seem to be referring to a user.")
        return

    try:
        user_chat = context.bot.get_chat(user_id)
        isvalid = True
        fban_user_id = user_chat.id
        fban_user_name = user_chat.first_name
    except BadRequest as excp:
        if not str(user_id).isdigit():
            send_message(message, excp.message)
            return
        elif len(str(user_id)) != 9:
            send_message(message, "That's so not a user!")
            return
        isvalid = False
        fban_user_id = int(user_id)
        fban_user_name = "user({})".format(user_id)
        # fban_user_lname = None
        # fban_user_uname = None

    if isvalid and user_chat.type != 'private':
        message.reply_text("That's so not a user!")
        return

    if isvalid:
        user_target = mention_html(fban_user_id, fban_user_name)
    else:
        user_target = fban_user_name

    fban, _, _ = sql.get_fban_user(fed_id, fban_user_id)
    if not fban:
        message.reply_text("This user is not fbanned!")
        return

    message.reply_text(
        "I'll give {} another chance in this federation".format(
            user_chat.first_name))

    chat_list = sql.all_fed_chats(fed_id)
    # Will send to current chat
    context.bot.send_message(chat.id,
                    "<b>Un-FedBan</b>"
                    "\n<b>Federation:</b> {}"
                    "\n<b>Federation Admin:</b> {}"
                    "\n<b>User:</b> {}"
                    "\n<b>User ID:</b> <code>{}</code>".format(info['fname'],
                                                                mention_html(user.id,
                                                                            user.first_name),
                                                                user_target,
                                                                fban_user_id),
                    parse_mode="HTML")
    # Send message to owner if fednotif is enabled
    if getfednotif:
        context.bot.send_message(info['owner'],
                        "<b>Un-FedBan</b>"
                        "\n<b>Federation:</b> {}"
                        "\n<b>Federation Admin:</b> {}"
                        "\n<b>User:</b> {}"
                        "\n<b>User ID:</b> <code>{}</code>".format(info['fname'],
                                                                    mention_html(user.id,
                                                                                user.first_name),
                                                                    user_target,
                                                                    fban_user_id),
                        parse_mode="HTML")
    # If fedlog is set, then send message, except fedlog is current chat
    get_fedlog = sql.get_fed_log(fed_id)
    if get_fedlog and int(get_fedlog) != int(chat.id):
        context.bot.send_message(get_fedlog,
                        "<b>Un-FedBan</b>"
                        "\n<b>Federation:</b> {}"
                        "\n<b>Federation Admin:</b> {}"
                        "\n<b>User:</b> {}"
                        "\n<b>User ID:</b> <code>{}</code>".format(info['fname'],
                                                                    mention_html(user.id,
                                                                                user.first_name),
                                                                    user_target,
                                                                    fban_user_id),
                        parse_mode="HTML")
    unfbanned_in_chats = 0
    for fedchats in chat_list:
        unfbanned_in_chats += 1
        try:
            member = context.bot.get_chat_member(fedchats, user_id)
            if member.status == 'kicked':
                context.bot.unban_chat_member(fedchats, user_id)
            # Do not spamming all fed chats
            """
            context.bot.send_message(chat, "<b>Un-FedBan</b>" \
                        "\n<b>Federation:</b> {}" \
                        "\n<b>Federation Admin:</b> {}" \
                        "\n<b>User:</b> {}" \
                        "\n<b>User ID:</b> <code>{}</code>".format(info['fname'], mention_html(user.id, user.first_name), user_target, fban_user_id), parse_mode="HTML")
            """
        except BadRequest as excp:
            if excp.message in UNFBAN_ERRORS:
                pass
            elif excp.message == "User_id_invalid":
                break
            else:
                LOGGER.warning(
                    "Could not fban on {} because: {}".format(
                        chat, excp.message))
        except TelegramError:
            pass

    try:
        x = sql.un_fban_user(fed_id, user_id)
        if not x:
            send_message(
                message,
                "Un-fban failed, this user may already be un-fedbanned!")
            return
    except BaseException as e:
        print(e)
    # UnFban for fed subscriber
    subscriber = list(sql.get_subscriber(fed_id))
    if len(subscriber) != 0:
        for fedsid in subscriber:
            all_fedschat = sql.all_fed_chats(fedsid)
            for fedschat in all_fedschat:
                try:
                    context.bot.unban_chat_member(fedchats, user_id)
                except BadRequest as excp:
                    if excp.message in FBAN_ERRORS:
                        try:
                            dispatcher.bot.getChat(fedschat)
                        except Unauthorized:
                            targetfed_id = sql.get_fed_id(fedschat)
                            sql.unsubs_fed(fed_id, targetfed_id)
                            LOGGER.info(
                                "Chat {} has unsub fed {} because I was kicked".format(
                                    fedschat, info['fname']))
                            continue
                    elif excp.message == "User_id_invalid":
                        break
                    else:
                        LOGGER.warning(
                            "Unable to fban on {} because: {}".format(
                                fedschat, excp.message))
                except TelegramError:
                    pass

    if unfbanned_in_chats == 0:
        send_message(message,
                     "This person has been un-fbanned in 0 chats.")
    if unfbanned_in_chats > 0:
        send_message(
            message,
            "This person has been un-fbanned in {} chats.".format(unfbanned_in_chats))
    # Also do not spamming all fed admins
    """
    FEDADMIN = sql.all_fed_users(fed_id)
    for x in FEDADMIN:
        getreport = sql.user_feds_report(x)
        if getreport == False:
            FEDADMIN.remove(x)
    send_to_list(bot, FEDADMIN,
            "<b>Un-FedBan</b>" \
            "\n<b>Federation:</b> {}" \
            "\n<b>Federation Admin:</b> {}" \
            "\n<b>User:</b> {}" \
            "\n<b>User ID:</b> <code>{}</code>".format(info['fname'], mention_html(user.id, user.first_name),
                                                    mention_html(user_chat.id, user_chat.first_name),
                                                            user_chat.id),
            html=True)
    """


@run_async
def set_frules(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)

    if not fed_id:
        message.reply_text(
            "This group is not in any federation!")
        return

    if is_user_fed_admin(fed_id, user.id) is False:
        message.reply_text("Only fed admins can do this!")
        return

    if len(args) >= 1:
        raw_text = message.text
        # use python's maxsplit to separate cmd and args
        args = raw_text.split(None, 1)
        if len(args) == 2:
            txt = args[1]
            # set correct offset relative to command
            offset = len(txt) - len(raw_text)
            markdown_rules = markdown_parser(
                txt, entities=message.parse_entities(), offset=offset)
        x = sql.set_frules(fed_id, markdown_rules)
        if not x:
            message.reply_text(
                "Whoa! There was an error while setting federation rules! If you wondered why please ask it in @LyndaEagleSupport !")
            return

        rules = sql.get_fed_info(fed_id)['frules']
        getfed = sql.get_fed_info(fed_id)
        get_fedlog = sql.get_fed_log(fed_id)
        if get_fedlog and eval(get_fedlog):
            context.bot.send_message(
                get_fedlog,
                "*{}* has updated federation rules for fed *{}*".format(
                    user.first_name,
                    getfed['fname']),
                parse_mode="markdown")
        message.reply_text(
            f"Rules have been changed to :\n{rules}!")
    else:
        message.reply_text(
            "Please write rules to set this up!")


@run_async
def get_frules(update: Update, context: CallbackContext):
    chat = update.effective_chat
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)
    if not fed_id:
        message.reply_text(
            "This group is not in any federation!")
        return

    rules = sql.get_frules(fed_id)
    text = "*Rules in this fed:*\n"
    text += rules
    message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@run_async
def fed_broadcast(update: Update, context: CallbackContext):
    args = context.args
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    if args:
        chat = update.effective_chat
        fed_id = sql.get_fed_id(chat.id)
        fedinfo = sql.get_fed_info(fed_id)
        if is_user_fed_owner(fed_id, user.id) is False:
            message.reply_text(
                "Only federation owners can do this!")
            return
        # Parsing md
        raw_text = message.text
        # use python's maxsplit to separate cmd and args
        args = raw_text.split(None, 1)
        txt = args[1]
        # set correct offset relative to command
        offset = len(txt) - len(raw_text)
        text_parser = markdown_parser(
            txt, entities=message.parse_entities(), offset=offset)
        text = text_parser
        try:
            broadcaster = user.first_name
        except BaseException:
            broadcaster = user.first_name + " " + user.last_name
        text += "\n\n- {}".format(mention_markdown(user.id, broadcaster))
        chat_list = sql.all_fed_chats(fed_id)
        failed = 0
        for chat in chat_list:
            title = "*New broadcast from Fed {}*\n".format(fedinfo['fname'])
            try:
                context.bot.sendMessage(chat, title + text, parse_mode="markdown")
            except TelegramError:
                try:
                    dispatcher.bot.getChat(chat)
                except Unauthorized:
                    failed += 1
                    sql.chat_leave_fed(chat)
                    LOGGER.info(
                        "Chat {} has left fed {} because I was punched".format(
                            chat, fedinfo['fname']))
                    continue
                failed += 1
                LOGGER.warning(
                    "Couldn't send broadcast to {}".format(
                        str(chat)))

        send_text = "The federation broadcast is complete"
        if failed >= 1:
            send_text += "{} the group failed to receive the message, probably because it left the Federation.".format(
                failed)
        message.reply_text(send_text)


@run_async
def fed_ban_list(update: Update, context: CallbackContext):
    chat_data = context.chat_data
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)
    info = sql.get_fed_info(fed_id)

    if not fed_id:
        message.reply_text(
            "This group is not a part of any federation!")
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        message.reply_text(
            "Only Federation owners can do this!")
        return

    user = update.effective_user
    chat = update.effective_chat
    getfban = sql.get_all_fban_users(fed_id)
    if len(getfban) == 0:
        message.reply_text(
            "The federation ban list of {} is empty".format(
                info['fname']), parse_mode=ParseMode.HTML)
        return

    if args:
        if args[0] == 'json':
            jam = time.time()
            new_jam = jam + 1800
            cek = get_chat(chat.id, chat_data)
            if cek.get('status'):
                if jam <= int(cek.get('value')):
                    waktu = time.strftime(
                        "%H:%M:%S %d/%m/%Y",
                        time.localtime(
                            cek.get('value')))
                    message.reply_text(
                        "You can backup your data once every 30 minutes!\nYou can back up data again at `{}`".format(
                            waktu),
                        parse_mode=ParseMode.MARKDOWN)
                    return
                else:
                    if user.id not in SUDO_USERS:
                        put_chat(chat.id, new_jam, chat_data)
            else:
                if user.id not in SUDO_USERS:
                    put_chat(chat.id, new_jam, chat_data)
            backups = ""
            for users in getfban:
                getuserinfo = sql.get_all_fban_users_target(fed_id, users)
                json_parser = {
                    "user_id": users,
                    "first_name": getuserinfo['first_name'],
                    "last_name": getuserinfo['last_name'],
                    "user_name": getuserinfo['user_name'],
                    "reason": getuserinfo['reason']}
                backups += json.dumps(json_parser)
                backups += "\n"
            with BytesIO(str.encode(backups)) as output:
                output.name = "lynda_fbanned_users.json"
                message.reply_document(
                    document=output,
                    filename="lynda_fbanned_users.json",
                    caption="Total {} User are blocked by the Federation {}.".format(
                        len(getfban),
                        info['fname']))
            return
        elif args[0] == 'csv':
            jam = time.time()
            new_jam = jam + 1800
            cek = get_chat(chat.id, chat_data)
            if cek.get('status'):
                if jam <= int(cek.get('value')):
                    waktu = time.strftime(
                        "%H:%M:%S %d/%m/%Y",
                        time.localtime(
                            cek.get('value')))
                    message.reply_text(
                        "You can back up data once every 30 minutes!\nYou can back up data again at `{}`".format(waktu),
                        parse_mode=ParseMode.MARKDOWN)
                    return
                else:
                    if user.id not in SUDO_USERS:
                        put_chat(chat.id, new_jam, chat_data)
            else:
                if user.id not in SUDO_USERS:
                    put_chat(chat.id, new_jam, chat_data)
            backups = "id,firstname,lastname,username,reason\n"
            for users in getfban:
                getuserinfo = sql.get_all_fban_users_target(fed_id, users)
                backups += "{user_id},{first_name},{last_name},{user_name},{reason}".format(
                    user_id=users,
                    first_name=getuserinfo['first_name'],
                    last_name=getuserinfo['last_name'],
                    user_name=getuserinfo['user_name'],
                    reason=getuserinfo['reason'])
                backups += "\n"
            with BytesIO(str.encode(backups)) as output:
                output.name = "lynda_fbanned_users.csv"
                message.reply_document(
                    document=output,
                    filename="lynda_fbanned_users.csv",
                    caption="Total {} User are blocked by Federation {}.".format(
                        len(getfban),
                        info['fname']))
            return

    text = "<b>{} users have been banned from the federation {}:</b>\n".format(
        len(getfban), info['fname'])
    for users in getfban:
        getuserinfo = sql.get_all_fban_users_target(fed_id, users)
        if not getuserinfo:
            text = "There are no users banned from the federation {}".format(
                info['fname'])
            break
        user_name = getuserinfo['first_name']
        if getuserinfo['last_name']:
            user_name += " " + getuserinfo['last_name']
        text += " - {} (<code>{}</code>)\n".format(mention_html(users,
                                                                user_name), users)

    try:
        message.reply_text(text, parse_mode=ParseMode.HTML)
    except BaseException:
        jam = time.time()
        new_jam = jam + 1800
        cek = get_chat(chat.id, chat_data)
        if cek.get('status'):
            if jam <= int(cek.get('value')):
                waktu = time.strftime(
                    "%H:%M:%S %d/%m/%Y",
                    time.localtime(
                        cek.get('value')))
                message.reply_text(
                    "You can back up data once every 30 minutes!\nYou can back up data again at `{}`".format(waktu),
                    parse_mode=ParseMode.MARKDOWN)
                return
            else:
                if user.id not in SUDO_USERS:
                    put_chat(chat.id, new_jam, chat_data)
        else:
            if user.id not in SUDO_USERS:
                put_chat(chat.id, new_jam, chat_data)
        cleanr = re.compile('<.*?>')
        cleantext = re.sub(cleanr, '', text)
        with BytesIO(str.encode(cleantext)) as output:
            output.name = "fbanlist.txt"
            message.reply_document(
                document=output,
                filename="fbanlist.txt",
                caption="The following is a list of users who are currently fbanned in the Federation {}.".format(
                    info['fname']))


@run_async
def fed_notif(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    fed_id = sql.get_fed_id(chat.id)
    message = update.effective_message
    if not fed_id:
        message.reply_text(
            "This group is not a part of any federation!")
        return

    if args:
        if args[0] in ("yes", "on"):
            sql.set_feds_setting(user.id, True)
            message.reply_text(
                "Reporting Federation back up! Every user who is fban / unfban you will be notified via PM.")
        elif args[0] in ("no", "off"):
            sql.set_feds_setting(user.id, False)
            message.reply_text(
                "Reporting Federation has stopped! Every user who is fban / unfban you will not be notified via PM.")
        else:
            message.reply_text(
                "Please enter `on`/`off`",
                parse_mode="markdown")
    else:
        getreport = sql.user_feds_report(user.id)
        message.reply_text(
            "Your current Federation report preferences: `{}`".format(getreport),
            parse_mode="markdown")


@run_async
def fed_chats(update: Update, _):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)
    info = sql.get_fed_info(fed_id)

    if not fed_id:
        message.reply_text(
            "This group is not a part of any federation!")
        return

    if is_user_fed_admin(fed_id, user.id) is False:
        message.reply_text(
            "Only federation admins can do this!")
        return

    getlist = sql.all_fed_chats(fed_id)
    if len(getlist) == 0:
        message.reply_text(
            "No users are fbanned from the federation {}".format(
                info['fname']), parse_mode=ParseMode.HTML)
        return

    text = "<b>New chat joined the federation {}:</b>\n".format(info['fname'])
    for chats in getlist:
        try:
            chat_name = dispatcher.bot.getChat(chats).title
        except Unauthorized:
            sql.chat_leave_fed(chats)
            LOGGER.info(
                "Chat {} has leave fed {} because I was kicked".format(
                    chats, info['fname']))
            continue
        text += " - {} (<code>{}</code>)\n".format(chat_name, chats)

    try:
        message.reply_text(text, parse_mode=ParseMode.HTML)
    except BaseException:
        cleanr = re.compile('<.*?>')
        cleantext = re.sub(cleanr, '', text)
        with BytesIO(str.encode(cleantext)) as output:
            output.name = "fedchats.txt"
            message.reply_document(
                document=output,
                filename="fedchats.txt",
                caption="Here is a list of all the chats that joined the federation {}.".format(
                    info['fname']))


@run_async
def fed_import_bans(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(message,
                    "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)
    getfed = sql.get_fed_info(fed_id)

    if not fed_id:
        message.reply_text(
            "This group is not a part of any federation!")
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        message.reply_text(
            "Only Federation owners can do this!")
        return

    if message.reply_to_message and message.reply_to_message.document:
        jam = time.time()
        new_jam = jam + 1800
        chat_data = context.chat_data
        cek = get_chat(chat.id, chat_data)
        if cek.get('status'):
            if jam <= int(cek.get('value')):
                waktu = time.strftime(
                    "%H:%M:%S %d/%m/%Y",
                    time.localtime(
                        cek.get('value')))
                message.reply_text(
                    "You can get your data once every 30 minutes!\nYou can get data again at `{}`".format(waktu),
                    parse_mode=ParseMode.MARKDOWN)
                return
            else:
                if user.id not in SUDO_USERS:
                    put_chat(chat.id, new_jam, chat_data)
        else:
            if user.id not in SUDO_USERS:
                put_chat(chat.id, new_jam, chat_data)
        success = 0
        failed = 0
        try:
            file_info = context.bot.get_file(message.reply_to_message.document.file_id)
        except BadRequest:
            message.reply_text(
                "Try downloading and re-uploading the file, this one seems broken!")
            return
        fileformat = message.reply_to_message.document.file_name.split('.')[-1]
        if fileformat == 'json':
            multi_fed_id = []
            multi_import_userid = []
            multi_import_firstname = []
            multi_import_lastname = []
            multi_import_username = []
            multi_import_reason = []
            with BytesIO() as file:
                file_info.download(out=file)
                file.seek(0)
                reading = file.read().decode('UTF-8')
                splitting = reading.split('\n')
                for x in splitting:
                    if x == '':
                        continue
                    try:
                        data = json.loads(x)
                    except json.decoder.JSONDecodeError:
                        failed += 1
                        continue
                    try:
                        import_userid = int(
                            data['user_id'])  # Make sure it int
                        import_firstname = str(data['first_name'])
                        import_lastname = str(data['last_name'])
                        import_username = str(data['user_name'])
                        import_reason = str(data['reason'])
                    except ValueError:
                        failed += 1
                        continue
                    # Checking user
                    if int(import_userid) == context.bot.id:
                        failed += 1
                        continue
                    if is_user_fed_owner(fed_id, import_userid):
                        failed += 1
                        continue
                    if is_user_fed_admin(fed_id, import_userid):
                        failed += 1
                        continue
                    if str(import_userid) == str(OWNER_ID):
                        failed += 1
                        continue
                    if int(import_userid) in SUDO_USERS:
                        failed += 1
                        continue
                    if int(import_userid) in SARDEGNA_USERS:
                        failed += 1
                        continue
                    if int(import_userid) in WHITELIST_USERS:
                        failed += 1
                        continue
                    multi_fed_id.append(fed_id)
                    multi_import_userid.append(str(import_userid))
                    multi_import_firstname.append(import_firstname)
                    multi_import_lastname.append(import_lastname)
                    multi_import_username.append(import_username)
                    multi_import_reason.append(import_reason)
                    success += 1
                sql.multi_fban_user(
                    multi_fed_id,
                    multi_import_userid,
                    multi_import_firstname,
                    multi_import_lastname,
                    multi_import_username,
                    multi_import_reason)
            text = "Blocks were successfully imported. {} people are blocked.".format(
                success)
            if failed >= 1:
                text += " {} Failed to import.".format(failed)
            get_fedlog = sql.get_fed_log(fed_id)
            if get_fedlog and eval(get_fedlog):
                teks = "Fed *{}* has successfully imported data. {} banned.".format(
                    getfed['fname'], success)
                if failed >= 1:
                    teks += " {} Failed to import.".format(failed)
                context.bot.send_message(get_fedlog, teks, parse_mode="markdown")
        elif fileformat == 'csv':
            multi_fed_id = []
            multi_import_userid = []
            multi_import_firstname = []
            multi_import_lastname = []
            multi_import_username = []
            multi_import_reason = []
            file_info.download(
                "fban_{}.csv".format(
                    message.reply_to_message.document.file_id))
            with open("fban_{}.csv".format(message.reply_to_message.document.file_id), 'r', encoding="utf8") as csvFile:
                reader = csv.reader(csvFile)
                for data in reader:
                    try:
                        import_userid = int(data[0])  # Make sure it int
                        import_firstname = str(data[1])
                        import_lastname = str(data[2])
                        import_username = str(data[3])
                        import_reason = str(data[4])
                    except ValueError:
                        failed += 1
                        continue
                    # Checking user
                    if int(import_userid) == context.bot.id:
                        failed += 1
                        continue
                    if is_user_fed_owner(fed_id, import_userid):
                        failed += 1
                        continue
                    if is_user_fed_admin(fed_id, import_userid):
                        failed += 1
                        continue
                    if str(import_userid) == str(OWNER_ID):
                        failed += 1
                        continue
                    if int(import_userid) in SUDO_USERS:
                        failed += 1
                        continue
                    if int(import_userid) in SARDEGNA_USERS:
                        failed += 1
                        continue
                    if int(import_userid) in WHITELIST_USERS:
                        failed += 1
                        continue
                    multi_fed_id.append(fed_id)
                    multi_import_userid.append(str(import_userid))
                    multi_import_firstname.append(import_firstname)
                    multi_import_lastname.append(import_lastname)
                    multi_import_username.append(import_username)
                    multi_import_reason.append(import_reason)
                    success += 1
                sql.multi_fban_user(
                    multi_fed_id,
                    multi_import_userid,
                    multi_import_firstname,
                    multi_import_lastname,
                    multi_import_username,
                    multi_import_reason)
            csvFile.close()
            os.remove(
                "fban_{}.csv".format(
                    message.reply_to_message.document.file_id))
            text = "Files were imported successfully. {} people banned.".format(
                success)
            if failed >= 1:
                text += " {} Failed to import.".format(failed)
            get_fedlog = sql.get_fed_log(fed_id)
            if get_fedlog and eval(get_fedlog):
                teks = "Fed *{}* has successfully imported data. {} banned.".format(
                    getfed['fname'], success)
                if failed >= 1:
                    teks += " {} Failed to import.".format(failed)
                context.bot.send_message(get_fedlog, teks, parse_mode="markdown")
        else:
            send_message(
                message,
                "This file is not supported.")
            return
        send_message(message, text)


@run_async
def del_fed_button(update: Update, _):
    query = update.callback_query
    fed_id = query.data.split("_")[1]
    if fed_id == 'cancel':
        query.message.edit_text("Federation deletion cancelled")
        return

    getfed = sql.get_fed_info(fed_id)
    if getfed:
        delete = sql.del_fed(fed_id)
        if delete:
            query.message.edit_text(
                "You have removed your Federation! Now all the Groups that are connected with `{}` do not have a Federation.".format(
                    getfed['fname']), parse_mode='markdown')


@run_async
def fed_stat_user(update: Update, context: CallbackContext):
    args = context.args
    message = update.effective_message
    if args and args[0].isdigit():
        user_id = args[0]
    else:
        user_id = extract_user(message, args)
    if user_id:
        if len(args) == 2 and args[0].isdigit():
            fed_id = args[1]
            user_name, reason, fbantime = sql.get_user_fban(
                fed_id, str(user_id))
            if fbantime:
                fbantime = time.strftime("%d/%m/%Y", time.localtime(fbantime))
            else:
                fbantime = "Unavaiable"
            if not user_name:
                send_message(
                    message,
                    "Fed {} not found!".format(fed_id),
                    parse_mode="markdown")
                return
            if user_name == "" or user_name is None:
                user_name = "He/she"
            if not reason:
                send_message(
                    message,
                    "{} is not banned in this federation!".format(user_name))
            else:
                teks = "{} banned in this federation because:\n`{}`\n*Banned at:* `{}`".format(
                    user_name, reason, fbantime)
                send_message(
                    message,
                    teks,
                    parse_mode="markdown")
            return
        user_name, fbanlist = sql.get_user_fbanlist(str(user_id))
        if user_name == "":
            try:
                user_name = context.bot.get_chat(user_id).first_name
            except BadRequest:
                user_name = "He/she"
            if user_name == "" or user_name is None:
                user_name = "He/she"
        if len(fbanlist) == 0:
            send_message(
                message,
                "{} is not banned in any federation!".format(user_name))
            return
        else:
            teks = "{} has been banned in this federation:\n".format(user_name)
            for x in fbanlist:
                teks += "- `{}`: {}\n".format(x[0], x[1][:20])
            teks += "\nIf you want to find out more about the reasons for Fedban specifically, use /fbanstat <FedID>"
            send_message(message, teks, parse_mode="markdown")

    elif not message.reply_to_message and not args:
        user_id = message.from_user.id
        user_name, fbanlist = sql.get_user_fbanlist(user_id)
        if user_name == "":
            user_name = message.from_user.first_name
        if len(fbanlist) == 0:
            send_message(
                message,
                "{} is not banned in any federation!".format(user_name))
        else:
            teks = "{} has been banned in this federation:\n".format(user_name)
            for x in fbanlist:
                teks += "- `{}`: {}\n".format(x[0], x[1][:20])
            teks += "\nIf you want to find out more about the reasons for Fedban specifically, use /fbanstat <FedID>"
            send_message(message, teks, parse_mode="markdown")

    else:
        fed_id = args[0]
        fedinfo = sql.get_fed_info(fed_id)
        if not fedinfo:
            send_message(
                message,
                "Fed {} not found!".format(fed_id))
            return
        name, reason, fbantime = sql.get_user_fban(
            fed_id, message.from_user.id)
        if fbantime:
            fbantime = time.strftime("%d/%m/%Y", time.localtime(fbantime))
        else:
            fbantime = "Unavaiable"
        if not name:
            name = message.from_user.first_name
        if not reason:
            send_message(message,
                        "{} is not banned in this federation".format(name))
            return
        send_message(
            message,
            "{} banned in this federation because:\n`{}`\n*Banned at:* `{}`".format(
                name,
                reason,
                fbantime),
            parse_mode="markdown")


@run_async
def set_fed_log(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(
            message,
            "This command is specific to the group, not to our pm!")
        return

    if args:
        fedinfo = sql.get_fed_info(args[0])
        if not fedinfo:
            send_message(
                message,
                "This Federation does not exist!")
            return
        isowner = is_user_fed_owner(args[0], user.id)
        if not isowner:
            send_message(message,
                        "Only federation creator can set federation logs.")
            return
        setlog = sql.set_fed_log(args[0], chat.id)
        if setlog:
            send_message(
                message,
                "Federation log `{}` has been set to {}".format(
                    fedinfo['fname'],
                    chat.title),
                parse_mode="markdown")
    else:
        send_message(message,
                    "You have not provided your federated ID!")


@run_async
def unset_fed_log(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(
            message,
            "This command is specific to the group, not to our pm!")
        return

    if args:
        fedinfo = sql.get_fed_info(args[0])
        if not fedinfo:
            send_message(message, "This Federation does not exist!")
            return
        isowner = is_user_fed_owner(args[0], user.id)
        if not isowner:
            send_message(
                message,
                "Only federation creator can set federation logs.")
            return
        setlog = sql.set_fed_log(args[0], None)
        if setlog:
            send_message(
                message,
                "Federation log `{}` has been revoked on {}".format(
                    fedinfo['fname'],
                    chat.title),
                parse_mode="markdown")
    else:
        send_message(message, "You have not provided your federated ID!")


@run_async
def subs_feds(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(
            message,
            "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)
    fedinfo = sql.get_fed_info(fed_id)

    if not fed_id:
        send_message(message, "This group is not in any federation!")
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        send_message(message, "Only fed owner can do this!")
        return

    if args:
        getfed = sql.search_fed_by_id(args[0])
        if not getfed:
            send_message(message, "Please enter a valid federation id.")
            return
        subfed = sql.subs_fed(args[0], fed_id)
        if subfed:
            send_message(
                message,
                "Federation `{}` has subscribe the federation `{}`. Every time there is a Fedban from that federation, this federation will also banned that user.".format(
                    fedinfo['fname'],
                    getfed['fname']),
                parse_mode="markdown")
            get_fedlog = sql.get_fed_log(args[0])
            if get_fedlog and int(get_fedlog) != int(chat.id):
                context.bot.send_message(
                    get_fedlog, "Federation `{}` has subscribe the federation `{}`".format(
                        fedinfo['fname'], getfed['fname']), parse_mode="markdown")
        else:
            send_message(
                message,
                "Federation `{}` already subscribe the federation `{}`.".format(
                    fedinfo['fname'],
                    getfed['fname']),
                parse_mode="markdown")
    else:
        send_message(message, "You have not provided your federated ID!")


@run_async
def unsubs_feds(update: Update, context: CallbackContext):
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(
            message,
            "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)
    fedinfo = sql.get_fed_info(fed_id)

    if not fed_id:
        send_message(message, "This group is not in any federation!")
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        send_message(message, "Only fed owner can do this!")
        return

    if args:
        getfed = sql.search_fed_by_id(args[0])
        if not getfed:
            send_message(message, "Please enter a valid federation id.")
            return
        subfed = sql.unsubs_fed(args[0], fed_id)
        if subfed:
            send_message(
                message,
                "Federation `{}` now unsubscribe fed `{}`.".format(
                    fedinfo['fname'],
                    getfed['fname']),
                parse_mode="markdown")
            get_fedlog = sql.get_fed_log(args[0])
            if get_fedlog and int(get_fedlog) != int(chat.id):
                context.bot.send_message(
                    get_fedlog,
                    "Federation `{}` has unsubscribe fed `{}`.".format(
                        fedinfo['fname'],
                        getfed['fname']),
                    parse_mode="markdown")
        else:
            send_message(
                message,
                "Federation `{}` is not subscribing `{}`.".format(
                    fedinfo['fname'],
                    getfed['fname']),
                parse_mode="markdown")
    else:
        send_message(message, "You have not provided your federated ID!")


@run_async
def get_myfedsubs(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == 'private':
        send_message(
            message,
            "This command is specific to the group, not to our pm!")
        return

    fed_id = sql.get_fed_id(chat.id)
    fedinfo = sql.get_fed_info(fed_id)

    if not fed_id:
        send_message(message, "This group is not in any federation!")
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        send_message(message, "Only fed owner can do this!")
        return

    try:
        getmy = sql.get_mysubs(fed_id)
    except BaseException:
        getmy = []

    if not getmy:
        send_message(
            message,
            "Federation `{}` is not subscribing any federation.".format(
                fedinfo['fname']),
            parse_mode="markdown")
        return
    else:
        listfed = "Federation `{}` is subscribing federation:\n".format(
            fedinfo['fname'])
        for x in getmy:
            listfed += "- `{}`\n".format(x)
        listfed += "\nTo get fed info `/fedinfo <fedid>`. To unsubscribe `/unsubfed <fedid>`."
        send_message(message, listfed, parse_mode="markdown")


@run_async
def get_myfeds_list(_, update: Update):
    user = update.effective_user
    message = update.effective_message
    fedowner = sql.get_user_owner_fed_full(user.id)
    if fedowner:
        text = "*You are owner of feds:\n*"
        for f in fedowner:
            text += "- `{}`: *{}*\n".format(f['fed_id'], f['fed']['fname'])
    else:
        text = "*You are not have any feds!*"
    send_message(message, text, parse_mode="markdown")


def is_user_fed_admin(fed_id, user_id):
    fed_admins = sql.all_fed_users(fed_id)
    if not fed_admins:
        return False
    return int(user_id) in fed_admins or int(user_id) == OWNER_ID


def is_user_fed_owner(fed_id, user_id):
    getsql = sql.get_fed_info(fed_id)
    if not getsql:
        return False
    getfedowner = eval(getsql['fusers'])
    if getfedowner is None or getfedowner is False:
        return False
    getfedowner = getfedowner['owner']
    return str(user_id) == getfedowner or int(user_id) == OWNER_ID


@run_async
def welcome_fed(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    fed_id = sql.get_fed_id(chat.id)
    fban, _, _ = sql.get_fban_user(fed_id, user.id)
    if fban:
        message.reply_text(
            "This user is banned in current federation! I will remove him.")
        context.bot.kick_chat_member(chat.id, user.id)
        return True
    else:
        return False


def __stats__():
    all_fbanned = sql.get_all_fban_users_global()
    all_feds = sql.get_all_feds_users_global()
    return "<b>• {} Users are banned, on {} Federation</b>".format(
        len(all_fbanned), len(all_feds))


def __user_info__(user_id, chat_id):
    fed_id = sql.get_fed_id(chat_id)
    if fed_id:
        fban, fbanreason, _ = sql.get_fban_user(fed_id, user_id)
        info = sql.get_fed_info(fed_id)
        infoname = info['fname']

        if int(info['owner']) == user_id:
            text = "This user is the owner of the current Federation: <b>{}</b>.".format(
                infoname)
        elif is_user_fed_admin(fed_id, user_id):
            text = "This user is the admin of the current Federation: <b>{}</b>.".format(
                infoname)

        elif fban:
            text = "Prohibited in the current Federation: <b>Yes</b>"
            text += "\n<b>Reason:</b> {}".format(fbanreason)
        else:
            text = "Prohibited in the current Federation: <b>No</b>"
    else:
        text = ""
    return text


# Temporary data
def put_chat(chat_id, value, chat_data):
    # print(chat_data)
    status = bool(value)
    chat_data[chat_id] = {'federation': {"status": status, "value": value}}


def get_chat(chat_id, chat_data):
    # print(chat_data)
    try:
        return chat_data[chat_id]['federation']
    except KeyError:
        return {"status": False, "value": False}


@run_async
def fed_owner_help(update: Update, _):
    message = update.effective_message
    text = "──「 <b>Fed Owner Only</b> 」──\n"
    text += "-> <code>/newfed</code> (fed_name)\n"
    text += "Creates a Federation, One allowed per user. Can also be used to rename the Fed. (max. 64 chars)\n"
    text += "-> <code>/delfed</code> (fed_id)\n"
    text += "Delete a Federation, and any information related to it. Will not cancel blocked users.\n"
    text += "-> <code>/fpromote</code> (user)\n"
    text += "assigns the user as a federation admin. Enables all commands for the user under <code>Fed Admins</code>.\n"
    text += "-> <code>/fdemote</code> (user)\n"
    text += "Drops the User from the admin Federation to a normal User.\n"
    text += "-> <code>/subfed`</code> (fed_id)\n"
    text += "Subscribes to a given fed ID, bans from that subscribed fed will also happen in your fed.\n"
    text += "-> <code>/unsubfed`</code> (fed_id)\n"
    text += "Unsubscribes to a given fed ID.\n"
    text += "-> <code>/setfedlog</code> (fed_id)\n"
    text += "Sets the group as a fed log report base for the federation.\n"
    text += "-> <code>/unsetfedlog</code> (fed_id)\n"
    text += "Removed the group as a fed log report base for the federation.\n"
    text += "-> <code>/fbroadcast</code> (message)\n"
    text += "Broadcasts a messages to all groups that have joined your fed.\n"
    text += "-> <code>/fedsubs</code>\n"
    text += "Shows the feds your group is subscribed to. <code>(broken rn)</code>"
    message.reply_text(text, parse_mode=ParseMode.HTML)


@run_async
def fed_admin_help(update: Update, _):
    message = update.effective_message
    text = "──「 <b>Fed Admins</b> 」──\n"
    text += "-> <code>/fban</code> (user) (reason)\n"
    text += "Fed bans a user.\n"
    text += "-> <code>/unfban</code> (user) (reason)\n"
    text += "Removes a user from a fed ban.\n"
    text += "-> <code>/fedinfo</code> (fed_id)\n"
    text += "Information about the specified Federation.\n"
    text += "-> <code>/joinfed</code> (fed_id)\n"
    text += "Join the current chat to the Federation. Only chat owners can do this.\n"
    text += "-> <code>/leavefed</code> (fed_id)\n"
    text += "Leave the Federation given. Only chat owners can do this.\n"
    text += "-> <code>/setfrules</code> (rules)\n"
    text += "Arrange Federation rules.\n"
    text += "-> <code>/fednotif</code> (on/off)\n"
    text += "Federation settings not in PM when there are users who are fbaned/unfbanned.\n"
    text += "-> <code>/frules</code>\n"
    text += "See Federation regulations.\n"
    text += "-> <code>/fedadmins</code>\n"
    text += "Show Federation admin.\n"
    text += "-> <code>/fbanlist</code>\n"
    text += "Displays all users who are victimized at the Federation at this time.\n"
    text += "-> <code>/fedchats</code>\n"
    text += "Get all the chats that are connected in the Federation.\n"
    message.reply_text(text, parse_mode=ParseMode.HTML)


@run_async
def fed_user_help(update: Update, _):
    message = update.effective_message
    message.reply_text("""──「 *Any user* 」──
-> `/fbanstat`
Shows if you/or the user you are replying to or their username is fbanned somewhere or not.
-> `/chatfed`
See the Federation in the current chat.
    """, parse_mode=ParseMode.MARKDOWN
)


__mod_name__ = "Federations"

__help__ = """
Everything is fun, until a spammer starts entering your group, and you have to block it. Then you need to start banning more, and more, and it hurts.
But then you have many groups, and you don't want this spammer to be in one of your groups - how can you deal? Do you have to manually block it, in all your groups?\n
*No longer!* With Federation, you can make a ban in one chat overlap with all other chats.\n
You can even designate federation admins, so your trusted admin can ban all the spammers from chats you want to protect.\n

──「 *Commands* 」──
Feds are now divided into 3 sections for your ease.
-> `/fedownerhelp`
Provides help for fed creation and owner only commands.
-> `/fedadminhelp`
Provides help for fed administration commands.
-> `/feduserhelp`
Provides help for commands anyone can use.
"""

NEW_FED_HANDLER = CommandHandler("newfed", new_fed)
DEL_FED_HANDLER = CommandHandler("delfed", del_fed, pass_args=True)
JOIN_FED_HANDLER = CommandHandler("joinfed", join_fed, pass_args=True)
LEAVE_FED_HANDLER = CommandHandler("leavefed", leave_fed, pass_args=True)
PROMOTE_FED_HANDLER = CommandHandler("fpromote", user_join_fed, pass_args=True)
DEMOTE_FED_HANDLER = CommandHandler("fdemote", user_demote_fed, pass_args=True)
INFO_FED_HANDLER = CommandHandler("fedinfo", fed_info, pass_args=True)
BAN_FED_HANDLER = DisableAbleCommandHandler(
    ["fban", "fedban"], fed_ban, pass_args=True)
UN_BAN_FED_HANDLER = CommandHandler("unfban", unfban, pass_args=True)
FED_BROADCAST_HANDLER = CommandHandler(
    "fbroadcast", fed_broadcast, pass_args=True)
FED_SET_RULES_HANDLER = CommandHandler("setfrules", set_frules, pass_args=True)
FED_GET_RULES_HANDLER = CommandHandler("frules", get_frules, pass_args=True)
FED_CHAT_HANDLER = CommandHandler("chatfed", fed_chat, pass_args=True)
FED_ADMIN_HANDLER = CommandHandler("fedadmins", fed_admin, pass_args=True)
FED_USERBAN_HANDLER = CommandHandler(
    "fbanlist",
    fed_ban_list,
    pass_args=True,
    pass_chat_data=True)
FED_NOTIF_HANDLER = CommandHandler("fednotif", fed_notif, pass_args=True)
FED_CHATLIST_HANDLER = CommandHandler("fedchats", fed_chats, pass_args=True)
FED_IMPORTBAN_HANDLER = CommandHandler(
    "importfbans", fed_import_bans, pass_chat_data=True)
FEDSTAT_USER = DisableAbleCommandHandler(
    ["fedstat", "fbanstat"], fed_stat_user, pass_args=True)
SET_FED_LOG = CommandHandler("setfedlog", set_fed_log, pass_args=True)
UNSET_FED_LOG = CommandHandler("unsetfedlog", unset_fed_log, pass_args=True)
SUBS_FED = CommandHandler("subfed", subs_feds, pass_args=True)
UNSUBS_FED = CommandHandler("unsubfed", unsubs_feds, pass_args=True)
MY_SUB_FED = CommandHandler("fedsubs", get_myfedsubs, pass_args=True)
MY_FEDS_LIST = CommandHandler("myfeds", get_myfeds_list)
DELETEBTN_FED_HANDLER = CallbackQueryHandler(del_fed_button, pattern=r"rmfed_")
FED_OWNER_HELP_HANDLER = CommandHandler("fedownerhelp", fed_owner_help)
FED_ADMIN_HELP_HANDLER = CommandHandler("fedadminhelp", fed_admin_help)
FED_USER_HELP_HANDLER = CommandHandler("feduserhelp", fed_user_help)

dispatcher.add_handler(NEW_FED_HANDLER)
dispatcher.add_handler(DEL_FED_HANDLER)
dispatcher.add_handler(JOIN_FED_HANDLER)
dispatcher.add_handler(LEAVE_FED_HANDLER)
dispatcher.add_handler(PROMOTE_FED_HANDLER)
dispatcher.add_handler(DEMOTE_FED_HANDLER)
dispatcher.add_handler(INFO_FED_HANDLER)
dispatcher.add_handler(BAN_FED_HANDLER)
dispatcher.add_handler(UN_BAN_FED_HANDLER)
dispatcher.add_handler(FED_BROADCAST_HANDLER)
dispatcher.add_handler(FED_SET_RULES_HANDLER)
dispatcher.add_handler(FED_GET_RULES_HANDLER)
dispatcher.add_handler(FED_CHAT_HANDLER)
dispatcher.add_handler(FED_ADMIN_HANDLER)
dispatcher.add_handler(FED_USERBAN_HANDLER)
dispatcher.add_handler(FED_NOTIF_HANDLER)
dispatcher.add_handler(FED_CHATLIST_HANDLER)
dispatcher.add_handler(FEDSTAT_USER)
dispatcher.add_handler(SET_FED_LOG)
dispatcher.add_handler(UNSET_FED_LOG)
dispatcher.add_handler(SUBS_FED)
dispatcher.add_handler(UNSUBS_FED)
dispatcher.add_handler(MY_SUB_FED)
dispatcher.add_handler(MY_FEDS_LIST)
dispatcher.add_handler(DELETEBTN_FED_HANDLER)
dispatcher.add_handler(FED_OWNER_HELP_HANDLER)
dispatcher.add_handler(FED_ADMIN_HELP_HANDLER)
dispatcher.add_handler(FED_USER_HELP_HANDLER)
