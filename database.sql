create table chats
(
    chat_id  integer not null
        constraint chats_pk
            primary key,
    username text,
    title    text
);

alter table chats
    owner to postgres;

create unique index chats_chat_id_uindex
    on chats (chat_id);

create table messages
(
    entry_id       serial  not null
        constraint messages_pk
            primary key,
    chat_id        integer not null
        constraint messages_chats_chat_id_fk
            references chats
            on update restrict on delete restrict,
    message_id     integer not null,
    datetime       timestamp,
    text           text,
    is_forward     boolean not null,
    file_path      text,
    file_mime_type text,
    reply_to       integer,
    sender_id      integer,
    is_scheduled   boolean not null
);

alter table messages
    owner to postgres;

create unique index messages_chat_id_message_id_is_scheduled_uindex
    on messages (chat_id, message_id, is_scheduled);

create table video_hashes
(
    hash     text    not null,
    entry_id integer not null
        constraint video_hashes_messages_entry_id_fk
            references messages
            on update restrict on delete restrict
);

alter table video_hashes
    owner to postgres;

