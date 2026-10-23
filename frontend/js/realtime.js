// One same-origin connection is shared by friend-request badges and open chats.
if (window.io) {
  const socket = window.io();
  const friendDots = document.querySelectorAll("[data-friend-dot]");

  socket.on("session_revoked", () => socket.disconnect());

  const showFriendDot = () => friendDots.forEach((dot) => dot.classList.remove("hidden"));
  const setFriendDot = (count) => {
    friendDots.forEach((dot) => dot.classList.toggle("hidden", Number(count) < 1));
  };

  // The server sends this only to this account's authenticated user room.
  socket.on("friend_request", (request) => {
    showFriendDot();
    const main = document.querySelector("main.content");
    if (!main) return;

    // Add the incoming request to the page immediately, without waiting for a refresh.
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
      const list = main.querySelector(".friend-list");
      main.insertBefore(section, list || null);
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
    [["accept", "Accept", "accept-button"], ["reject", "Decline", "reject-button"]].forEach(([value, label, className]) => {
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

  const chatLayout = document.querySelector(".chat-layout[data-conversation-id]");
  if (chatLayout) {
    const conversationId = Number(chatLayout.dataset.conversationId);
    const messageList = document.getElementById("message-list");
    const messageForm = document.getElementById("message-form");
    const messageInput = document.getElementById("message-input");
    let roomReady = false;

    socket.on("connect", () => {
      socket.emit("join_chat", { conversation_id: conversationId }, (result) => {
        roomReady = Boolean(result && result.ok);
      });
    });

    socket.on("new_message", (message) => {
      if (Number(message.conversation_id) !== conversationId || !messageList) return;
      messageList.querySelector(".empty-state")?.remove();

      // Use textContent so message text is displayed as text, never interpreted as HTML.
      const article = document.createElement("article");
      article.className = "message";
      const sender = document.createElement("strong");
      sender.textContent = message.display_name;
      const body = document.createElement("p");
      body.textContent = message.body;
      const time = document.createElement("time");
      time.textContent = new Date(message.created_at).toLocaleString();
      article.append(sender, body, time);
      messageList.append(article);
      messageList.scrollTop = messageList.scrollHeight;
    });

    messageForm?.addEventListener("submit", (event) => {
      if (!socket.connected || !roomReady) return; // Keep the regular HTTP form as a fallback.
      event.preventDefault();
      const body = messageInput.value.trim();
      if (!body) return;
      socket.emit("send_message", { conversation_id: conversationId, body }, (result) => {
        if (result && result.ok) {
          messageInput.value = "";
          messageInput.focus();
        }
      });
    });
  }
}
