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
