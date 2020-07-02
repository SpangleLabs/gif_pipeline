
create table if not exists chats
(
    chat_id  int not null
        constraint chats_pk
            primary key,
    username text,
    title    text,
    chat_type text not null
);

create unique index if not exists chats_chat_id_uindex
    on chats (chat_id);

create table if not exists messages
(
    entry_id       integer not null
        constraint messages_pk
            primary key autoincrement,
    chat_id        integer not null
        references chats
            on update restrict on delete restrict,
    message_id     int     not null,
    datetime       text,
    text           text,
    is_forward     boolean not null,
    file_path      text,
    file_mime_type text,
    reply_to       integer
        constraint messages_messages_message_id_fk
            references messages (message_id)
            on update restrict on delete restrict,
    sender_id      integer,
    is_scheduled   boolean not null
);

create unique index if not exists messages_chat_id_message_id_is_scheduled_uindex
	on messages (chat_id, message_id, is_scheduled);

create table if not exists video_hashes
(
    hash     text    not null,
    entry_id integer not null
        references messages
            on update restrict on delete restrict
);

create unique index if not exists video_hashes_hash_entry_id_uindex
	on video_hashes (hash, entry_id);
