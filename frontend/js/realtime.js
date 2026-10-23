// Connect the browser to the Python Socket.IO server using its login cookie.
function startRealtime() {
  if (!window.io) return;
  // Register every handler before opening the connection, so no first event is missed.
  const socket = window.io({ autoConnect: false });
  const friendDots = document.querySelectorAll("[data-friend-dot]");
  const chatDots = document.querySelectorAll("[data-chat-dot]");

  const showFriendDot = () => friendDots.forEach((dot) => dot.classList.remove("hidden"));
  const setFriendDot = (count) => friendDots.forEach((dot) => {
    dot.classList.toggle("hidden", Number(count) < 1);
  });
  const setChatDot = (count) => chatDots.forEach((dot) => {
    dot.classList.toggle("hidden", Number(count) < 1);
  });

  socket.on("friend_request", (request) => {
    showFriendDot();
    const main = document.querySelector("main.content");
    if (!main) return;

    let section = document.getElementById("friend-requests");
    if (!section) {
      section = document.createElement("section");
      section.className = "requests";
      section.id = "friend-requests";
      const heading = document.createElement("h2");
      heading.append("Friend requests ");
      const count = document.createElement("span");
      count.dataset.requestCount = "";
      count.textContent = "0";
      heading.append(count);
      section.append(heading);
      main.insertBefore(section, main.querySelector(".friend-list"));
    }

    const count = section.querySelector("[data-request-count]");
    if (count) count.textContent = String(Number(count.textContent) + 1);
    const row = document.createElement("div");
    row.className = "request-row";
    if (request.has_avatar) {
      const avatar = document.createElement("img");
      avatar.className = "avatar";
      avatar.src = `/users/${request.sender_id}/avatar`;
      avatar.alt = "";
      row.append(avatar);
    } else {
      const avatar = document.createElement("span");
      avatar.className = "avatar";
      avatar.textContent = request.name.slice(0, 1).toUpperCase();
      row.append(avatar);
    }
    const info = document.createElement("div");
    info.className = "friend-info";
    const name = document.createElement("strong");
    name.textContent = request.name;
    const username = document.createElement("small");
    username.textContent = `@${request.username}`;
    info.append(name, username);
    row.append(info);

    const actions = document.createElement("form");
    actions.className = "request-actions";
    actions.action = `/friends/request/${request.request_id}`;
    actions.method = "post";
    [["accept", "Accept", "accept-button"], ["reject", "Decline", "reject-button"]]
      .forEach(([value, label, className]) => {
        const button = document.createElement("button");
        button.name = "action";
        button.value = value;
        button.className = className;
        button.textContent = label;
        actions.append(button);
      });
    row.append(actions);
    section.append(row);
  });

  socket.on("friend_requests_count", (data) => setFriendDot(data.count));
  socket.on("unread_count", (data) => setChatDot(data.count));
  socket.on("unread_message", (data) => {
    const conversationId = Number(data.conversation_id);
    const activeConversation = Number(document.querySelector(".chat-layout[data-conversation-id]")?.dataset.conversationId || 0);
    const chip = document.querySelector(`.conversation-chip[data-conversation-id="${conversationId}"]`);

    if (chip && data.body) {
      const preview = chip.querySelector(".conversation-copy small");
      if (preview) preview.textContent = data.body;
    }
    if (activeConversation === conversationId) {
      socket.emit("mark_read", { conversation_id: conversationId });
      return;
    }

    setChatDot(1);
    chip?.querySelector("[data-conversation-dot]")?.classList.remove("hidden");
  });
  socket.on("session_revoked", () => socket.disconnect());

  const chat = document.querySelector(".chat-layout[data-conversation-id]");
  const status = document.getElementById("socket-status");
  const setStatus = (text, connected) => {
    if (!status) return;
    status.textContent = text;
    status.dataset.connected = String(connected);
  };
  socket.on("connect", () => setStatus("Live", true));
  socket.on("disconnect", () => setStatus("Reconnecting…", false));
  socket.on("connect_error", () => setStatus("Offline · retrying", false));

  if (chat) {
    const conversationId = Number(chat.dataset.conversationId);
    const messageList = document.getElementById("message-list");
    const form = document.getElementById("message-form");
    const input = document.getElementById("message-input");
    let joinedRoom = false;

    const scrollToLatest = () => {
      if (messageList) messageList.scrollTo({ top: messageList.scrollHeight, behavior: "auto" });
    };

    // Place the newest messages and input cursor where the user can continue chatting.
    requestAnimationFrame(() => {
      scrollToLatest();
      input?.focus();
    });

    socket.on("connect", () => {
      socket.emit("join_chat", { conversation_id: conversationId }, (result) => {
        joinedRoom = Boolean(result && result.ok);
        scrollToLatest();
      });
    });
    socket.on("disconnect", () => { joinedRoom = false; });

    socket.on("new_message", (message) => {
      if (Number(message.conversation_id) !== conversationId || !messageList) return;
      messageList.querySelector(".chat-empty")?.remove();

      // Insert message content as text, never as HTML.
      const item = document.createElement("article");
      item.className = "message";
      const sender = document.createElement("strong");
      sender.textContent = message.display_name;
      const body = document.createElement("p");
      body.textContent = message.body;
      const time = document.createElement("time");
      time.textContent = new Date(message.created_at).toLocaleString();
      item.append(sender, body, time);
      messageList.append(item);
      const chip = document.querySelector(`.conversation-chip[data-conversation-id="${conversationId}"]`);
      const preview = chip?.querySelector(".conversation-copy small");
      if (preview) preview.textContent = message.body;
      scrollToLatest();
      input?.focus();
      if (Number(message.sender_id) !== Number(chat.dataset.userId)) {
        socket.emit("mark_read", { conversation_id: conversationId });
      }
    });

    form?.addEventListener("submit", async (event) => {
      // Keep the page and cursor in place, including while Socket.IO reconnects.
      event.preventDefault();
      const body = input.value.trim();
      if (!body) return;
      const restoreCursor = () => {
        input.focus({ preventScroll: true });
        input.setSelectionRange(input.value.length, input.value.length);
      };
      const clearAfterSent = () => {
        input.value = "";
        restoreCursor();
      };

      if (socket.connected && joinedRoom) {
        socket.timeout(8000).emit("send_message", { conversation_id: conversationId, body }, (error, result) => {
          if (!error && result?.ok) {
            clearAfterSent();
            return;
          }
          setStatus("Retrying message…", false);
          sendWithHttpFallback(body).then(clearAfterSent).catch(() => {
            setStatus("Message not sent · retry", false);
            restoreCursor();
          });
        });
        return;
      }

      sendWithHttpFallback(body).then(clearAfterSent).catch(() => {
        setStatus("Message not sent · retry", false);
        restoreCursor();
      });
    });

    async function sendWithHttpFallback(body) {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body: new URLSearchParams({ body }),
        credentials: "same-origin",
      });
      if (!response.ok || response.redirected && response.url.includes("/login")) {
        throw new Error("Message request failed");
      }
    }
  }

  socket.connect();
}

if (window.io) {
  startRealtime();
} else {
  // The alternate CDN lets the page recover if the primary client CDN is blocked.
  const client = document.createElement("script");
  client.src = "https://cdn.jsdelivr.net/npm/socket.io-client@4.8.1/dist/socket.io.min.js";
  client.onload = startRealtime;
  client.onerror = () => {
    const status = document.getElementById("socket-status");
    if (status) status.textContent = "Realtime client unavailable";
  };
  document.head.append(client);
}
