(() => {
  const rootPath = document.body.dataset.rootPath || "";
  const knownStates = new Set(["WORKING", "WAITING_APPROVAL", "IDLE", "FAILED", "OFFLINE"]);
  const connection = document.querySelector("[data-connection-status]");
  const detailEmpty = document.querySelector("[data-detail-empty]");
  const detailContent = document.querySelector("[data-detail-content]");
  const detailTitle = document.querySelector("[data-detail-title]");
  const detailStatus = document.querySelector("[data-detail-status]");
  const detailAgent = document.querySelector("[data-detail-agent]");
  const detailMission = document.querySelector("[data-detail-mission]");
  const rooms = new Map(
    [...document.querySelectorAll("[data-room-key]")].map((element) => [element.dataset.roomKey, element])
  );
  let latestRooms = new Map();
  let selectedRoomKey = null;

  const readableState = (state) => {
    const normalized = knownStates.has(state) ? state : "OFFLINE";
    return normalized
      .toLowerCase()
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  };

  const normalizeRoom = (room = {}) => {
    const state = knownStates.has(room.state) ? room.state : "OFFLINE";
    return {
      key: String(room.key || ""),
      label: String(room.label || room.key || "Unknown room"),
      state,
      mission_title: room.mission_title ? String(room.mission_title) : null,
      count: Number.isFinite(room.count) ? room.count : null,
      agent:
        room.agent && typeof room.agent === "object"
          ? {
              key: String(room.agent.key || ""),
              display_name: String(room.agent.display_name || room.agent.key || "Unknown"),
            }
          : null,
    };
  };

  const countCopy = (room) => {
    if (room.key === "approvals") {
      return `${room.count ?? 0} pending approval${room.count === 1 ? "" : "s"}`;
    }
    if (room.key === "knowledge") {
      return `${room.count ?? 0} memor${room.count === 1 ? "y" : "ies"}`;
    }
    return null;
  };

  const renderRoom = (room) => {
    const element = rooms.get(room.key);
    if (!element) return;

    element.dataset.roomState = room.state;
    if (element.hasAttribute("data-agent-state")) {
      element.dataset.agentState = room.agent ? room.state : "OFFLINE";
    }

    const status = element.querySelector("[data-room-status]");
    if (status) status.textContent = `Status: ${readableState(room.state)}`;

    const mission = element.querySelector("[data-room-mission]");
    if (mission) mission.textContent = room.mission_title || "No active mission";

    const count = element.querySelector("[data-room-count]");
    if (count) count.textContent = countCopy(room) || "0";
  };

  const renderDetail = (roomKey) => {
    const room = latestRooms.get(roomKey);
    if (!room || !detailContent || !detailEmpty) return;

    detailEmpty.hidden = true;
    detailContent.hidden = false;
    detailTitle.textContent = room.label;
    detailStatus.textContent = readableState(room.state);
    detailAgent.textContent = room.agent ? room.agent.display_name : "Shared system room";
    detailMission.textContent = room.mission_title || countCopy(room) || "No active mission";

    rooms.forEach((element, key) => {
      element.setAttribute("aria-pressed", key === roomKey ? "true" : "false");
    });
  };

  const markDisconnected = () => {
    if (connection) {
      connection.textContent = "State feed offline";
      connection.dataset.status = "offline";
    }
    rooms.forEach((element) => {
      if (element.hasAttribute("data-agent-state")) {
        element.dataset.agentState = "OFFLINE";
        element.dataset.roomState = "OFFLINE";
        const status = element.querySelector("[data-room-status]");
        if (status) status.textContent = "Status: Offline";
      }
    });
  };

  const refresh = async () => {
    try {
      const response = await fetch(`${rootPath}/api/hq/state`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HQ state request failed: ${response.status}`);
      const payload = await response.json();
      const normalized = Array.isArray(payload.rooms) ? payload.rooms.map(normalizeRoom) : [];
      latestRooms = new Map(normalized.map((room) => [room.key, room]));
      normalized.forEach(renderRoom);

      if (connection) {
        connection.textContent = "State feed online";
        connection.dataset.status = "online";
      }
      if (selectedRoomKey) renderDetail(selectedRoomKey);
    } catch (_error) {
      markDisconnected();
    }
  };

  rooms.forEach((element, key) => {
    element.setAttribute("aria-pressed", "false");
    element.addEventListener("click", () => {
      selectedRoomKey = key;
      renderDetail(key);
    });
  });

  refresh();
  window.setInterval(refresh, 10000);
})();

/* ==========================================================
   SysAdmin Chat v1
   ========================================================== */

(() => {
  const panel = document.getElementById("sysadmin-chat");
  const close = document.getElementById("sysadmin-chat-close");
  const messages = document.getElementById("sysadmin-chat-messages");
  const form = document.getElementById("sysadmin-chat-form");
  const input = document.getElementById("sysadmin-chat-input");
  const send = document.getElementById("sysadmin-chat-send");
  const status = document.getElementById("sysadmin-chat-status");

  if (!panel || !messages || !form || !input || !send || !status) {
    return;
  }

  const rootPath =
    (document.body.dataset.rootPath || "").replace(/\/$/, "");

  let conversationId = null;
  let pollingMissionId = null;

  function api(path) {
    return `${rootPath}${path}`;
  }

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');

    if (meta?.content) {
      return meta.content;
    }

    const field = document.querySelector(
      '[name="csrf_token"]'
    );

    if (field?.value) {
      return field.value;
    }

    if (document.body.dataset.csrfToken) {
      return document.body.dataset.csrfToken;
    }

    return "";
  }

  function writeHeaders() {
    return {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken(),
    };
  }

  function setStatus(text) {
    status.textContent = text;
  }

  function renderMarkdown(target, content) {
    const inline = (parent, text) => {
      const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
      parts.filter(Boolean).forEach((part) => {
        if (part.startsWith("`") && part.endsWith("`")) {
          const code = document.createElement("code");
          code.textContent = part.slice(1, -1);
          parent.appendChild(code);
        } else if (part.startsWith("**") && part.endsWith("**")) {
          const strong = document.createElement("strong");
          strong.textContent = part.slice(2, -2);
          parent.appendChild(strong);
        } else {
          parent.appendChild(document.createTextNode(part));
        }
      });
    };

    let list = null;
    content.split(/\r?\n/).forEach((line) => {
      if (!line.trim()) {
        list = null;
        return;
      }
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      const bullet = line.match(/^[-*]\s+(.+)$/);
      let element;
      if (heading) {
        list = null;
        element = document.createElement(`h${heading[1].length + 3}`);
        inline(element, heading[2]);
        target.appendChild(element);
      } else if (bullet) {
        if (!list) {
          list = document.createElement("ul");
          target.appendChild(list);
        }
        element = document.createElement("li");
        inline(element, bullet[1]);
        list.appendChild(element);
      } else {
        list = null;
        element = document.createElement("p");
        inline(element, line);
        target.appendChild(element);
      }
    });
  }

  function appendMessage(role, content) {
    if (!content) {
      return;
    }

    const row = document.createElement("div");
    row.className =
      `sysadmin-chat__message sysadmin-chat__message--${role}`;

    const author = document.createElement("strong");
    author.className = "sysadmin-chat__author";
    author.textContent = role === "user" ? "You" : "SysAdmin";

    const body = document.createElement("div");
    body.className = "sysadmin-chat__message-body";
    renderMarkdown(body, content);

    row.append(author, body);
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;
  }

  function resultMessage(result) {
    if (!result?.message) {
      return null;
    }

    if (typeof result.message === "string") {
      return result.message;
    }

    return result.message.content || null;
  }

  async function request(path, options = {}) {
    const response = await fetch(api(path), {
      credentials: "same-origin",
      ...options,
    });

    if (!response.ok) {
      let message = `Request failed (${response.status})`;

      try {
        const payload = await response.json();

        if (payload.detail) {
          message =
            typeof payload.detail === "string"
              ? payload.detail
              : JSON.stringify(payload.detail);
        }
      } catch (_) {
        // Keep generic HTTP message.
      }

      throw new Error(message);
    }

    return response.json();
  }

  async function ensureConversation() {
    if (conversationId) {
      return conversationId;
    }

    const existing = await request(
      "/api/chat/conversations"
    );

    if (existing.conversations?.length) {
      conversationId = existing.conversations[0].id;
      return conversationId;
    }

    const created = await request(
      "/api/chat/conversations",
      {
        method: "POST",
        headers: writeHeaders(),
      }
    );

    conversationId = created.conversation.id;
    return conversationId;
  }

  async function loadMessages() {
    const id = await ensureConversation();

    const payload = await request(
      `/api/chat/conversations/${id}/messages`
    );

    messages.replaceChildren();

    if (!payload.messages?.length) {
      const welcome = document.createElement("div");
      welcome.className = "sysadmin-chat__welcome";
      welcome.textContent =
        "Ask SysAdmin about AI HQ health, service status, or recent logs.";
      messages.appendChild(welcome);
      return;
    }

    for (const message of payload.messages) {
      appendMessage(message.role, message.content);
    }
  }

  function pollMission(missionId) {
    if (!missionId) {
      return;
    }

    pollingMissionId = missionId;

    const poll = async () => {
      if (pollingMissionId !== missionId) {
        return;
      }

      try {
        const result = await request(
          `/api/chat/conversations/${conversationId}` +
          `/missions/${missionId}`
        );

        if (result.state === "pending") {
          setStatus("Checking AI HQ…");
          setTimeout(poll, 1200);
          return;
        }

        pollingMissionId = null;
        setStatus("Ready");

        const content = resultMessage(result);

        if (content) {
          appendMessage("assistant", content);
        } else {
          await loadMessages();
        }
      } catch (error) {
        pollingMissionId = null;
        setStatus("Unavailable");
        appendMessage(
          "assistant",
          `Unable to refresh mission: ${error.message}`
        );
      }
    };

    setTimeout(poll, 800);
  }

  async function submitMessage(text) {
    const id = await ensureConversation();

    appendMessage("user", text);
    setStatus("Thinking…");

    const result = await request(
      `/api/chat/conversations/${id}/messages`,
      {
        method: "POST",
        headers: writeHeaders(),
        body: JSON.stringify({ text }),
      }
    );

    const content = resultMessage(result);

    if (content) {
      appendMessage("assistant", content);
    }

    if (
      result.state === "pending" &&
      result.mission_id
    ) {
      setStatus("Checking AI HQ…");
      pollMission(result.mission_id);
      return;
    }

    setStatus("Ready");
  }

  function closeSysAdminChat() {
    panel.hidden = true;
  }

  async function openSysAdminChat() {
    panel.hidden = false;
    setStatus("Loading…");

    try {
      await loadMessages();
      setStatus("Ready");
      input.focus();
    } catch (error) {
      setStatus("Unavailable");
      appendMessage(
        "assistant",
        `SysAdmin Chat unavailable: ${error.message}`
      );
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const text = input.value.trim();

    if (!text) {
      return;
    }

    input.value = "";
    input.disabled = true;
    send.disabled = true;

    try {
      await submitMessage(text);
    } catch (error) {
      setStatus("Unavailable");
      appendMessage(
        "assistant",
        `SysAdmin Chat unavailable: ${error.message}`
      );
    } finally {
      input.disabled = false;
      send.disabled = false;
      input.focus();
    }
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  if (close) {
    close.addEventListener("click", closeSysAdminChat);
  }

  document.addEventListener("click", (event) => {
    const room = event.target.closest(
      '[data-room-key="sysadmin"]'
    );

    if (room) {
      openSysAdminChat();
    }
  });

  document.addEventListener("keydown", (event) => {
    const room = event.target.closest(
      '[data-room-key="sysadmin"]'
    );

    if (
      room &&
      (event.key === "Enter" || event.key === " ")
    ) {
      setTimeout(openSysAdminChat, 0);
    }
  });
})();
