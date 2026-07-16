/* Open-DAM Premiere panel.
 *
 * Architecture: this JS runs in the CEP browser context with Node enabled.
 * All DAM logic stays in the `dam` CLI (spawned via child_process); all
 * Premiere-side actions (open/save/close project) go through the
 * ExtendScript bridge in jsx/host.jsx via evalScript. The panel itself is
 * just glue and rendering — it holds no lock logic of its own.
 */

var cp = require("child_process");

var REFRESH_MS = 30000;
var state = { busy: false, projects: [], confirmingRelease: null };

/* ---------- ExtendScript bridge ---------- */

function evalScript(script) {
  return new Promise(function (resolve) {
    window.__adobe_cep__.evalScript(script, resolve);
  });
}

/* ---------- settings ---------- */

function getSettings() {
  return {
    repoPath: localStorage.getItem("odam.repoPath") || "",
    damPath: localStorage.getItem("odam.damPath") || "",
  };
}

function saveSettingsValues(repoPath, damPath) {
  localStorage.setItem("odam.repoPath", repoPath);
  localStorage.setItem("odam.damPath", damPath);
}

function detectDamPath() {
  // A login shell so the user's normal PATH (pipx, venv shims, etc.) applies.
  return new Promise(function (resolve) {
    cp.exec("/bin/zsh -lc 'command -v dam'", function (err, stdout) {
      resolve(err ? "" : stdout.trim());
    });
  });
}

/* ---------- running dam ---------- */

function runDam(args) {
  var s = getSettings();
  return new Promise(function (resolve, reject) {
    if (!s.damPath) return reject(new Error("dam command not configured"));
    if (!s.repoPath) return reject(new Error("project library folder not configured"));
    cp.execFile(
      s.damPath,
      args.concat(["--repo", s.repoPath]),
      { timeout: 120000 },
      function (err, stdout, stderr) {
        if (err) {
          reject(new Error((stdout || "") + (stderr || "") || err.message));
        } else {
          resolve(stdout);
        }
      }
    );
  });
}

/* ---------- UI plumbing ---------- */

function el(id) { return document.getElementById(id); }

function setStatus(msg, isError) {
  var line = el("statusLine");
  line.textContent = msg || "";
  line.className = isError ? "error" : "";
}

function setBusy(busy) {
  state.busy = busy;
  var buttons = document.querySelectorAll("button");
  for (var i = 0; i < buttons.length; i++) buttons[i].disabled = busy;
}

function showSetup(errorMsg) {
  el("main").classList.add("hidden");
  el("setup").classList.remove("hidden");
  var s = getSettings();
  el("repoPath").value = s.repoPath;
  el("damPath").value = s.damPath;
  el("setupError").textContent = errorMsg || "";
}

function showMain() {
  el("setup").classList.add("hidden");
  el("main").classList.remove("hidden");
}

/* ---------- rendering ---------- */

function render() {
  var container = el("projects");
  container.innerHTML = "";
  if (!state.projects.length) {
    container.textContent = "No projects in the library yet.";
    return;
  }
  state.projects.forEach(function (p) {
    var row = document.createElement("div");
    row.className = "project";

    var name = document.createElement("span");
    name.className = "name";
    name.textContent = p.name;
    name.title = p.rel_path;
    row.appendChild(name);

    var badge = document.createElement("span");
    badge.className = "badge " + (p.mine ? "mine" : p.status === "locked" ? "locked" : "free");
    badge.textContent = p.mine ? "yours" : p.status === "locked" ? "locked" : "available";
    row.appendChild(badge);

    if (p.status === "locked" && !p.mine) {
      var who = document.createElement("span");
      who.className = "who";
      who.textContent = p.locked_by;
      who.title = p.locked_by + " since " + p.locked_at;
      row.appendChild(who);
    }

    if (p.mine) {
      if (state.confirmingRelease === p.name) {
        // CEF doesn't reliably support window.confirm, so confirmation is a
        // second in-row click instead of a dialog.
        row.appendChild(actionButton("Really release?", "danger", function () {
          state.confirmingRelease = null;
          release(p);
        }));
        row.appendChild(actionButton("Keep", "", function () {
          state.confirmingRelease = null;
          render();
        }));
      } else {
        row.appendChild(actionButton("Check In", "primary", function () { checkin(p); }));
        row.appendChild(actionButton("Release", "danger", function () {
          state.confirmingRelease = p.name;
          render();
        }));
      }
    } else if (p.status !== "locked") {
      row.appendChild(actionButton("Checkout", "primary", function () { checkout(p); }));
    }

    container.appendChild(row);
  });
}

function actionButton(label, cls, onClick) {
  var b = document.createElement("button");
  b.textContent = label;
  b.className = cls;
  b.addEventListener("click", onClick);
  return b;
}

/* ---------- actions ---------- */

function refresh(silent) {
  if (state.busy) return Promise.resolve();
  if (!silent) setStatus("Refreshing…");
  return runDam(["list", "--json"])
    .then(function (out) {
      state.projects = JSON.parse(out).projects;
      render();
      if (!silent) setStatus("");
      showMain();
    })
    .catch(function (e) {
      showSetup("Could not talk to dam: " + e.message);
    });
}

function checkout(p) {
  setBusy(true);
  setStatus("Checking out " + p.name + "…");
  runDam(["checkout", p.name, "--no-launch"])
    .then(function () {
      return evalScript('ODAM_openProject(' + JSON.stringify(p.path) + ')');
    })
    .then(function (result) {
      if (result !== "ok") throw new Error(result);
      setStatus(p.name + " is yours — opened in Premiere.");
    })
    .catch(function (e) { setStatus(e.message, true); })
    .then(function () { setBusy(false); return refresh(true); });
}

function checkin(p) {
  setBusy(true);
  setStatus("Checking in " + p.name + "…");
  evalScript("ODAM_currentProjectPath()")
    .then(function (openPath) {
      if (openPath === p.path) {
        // The panel's superpower: save + close from inside Premiere, so the
        // .prproj on disk is final before the commit happens.
        setStatus("Saving and closing in Premiere…");
        return evalScript("ODAM_saveAndCloseProject()").then(function (result) {
          if (result !== "ok") throw new Error(result);
        });
      }
      if (openPath) {
        // A different project is open — that's fine, nothing to save here.
        return;
      }
    })
    .then(function () {
      setStatus("Saving to team library…");
      return runDam(["checkin", p.name, "--yes"]);
    })
    .then(function () { setStatus(p.name + " checked in."); })
    .catch(function (e) { setStatus(e.message, true); })
    .then(function () { setBusy(false); return refresh(true); });
}

function release(p) {
  setBusy(true);
  setStatus("Releasing " + p.name + "…");
  runDam(["release", p.name])
    .then(function () { setStatus(p.name + " released."); })
    .catch(function (e) { setStatus(e.message, true); })
    .then(function () { setBusy(false); return refresh(true); });
}

function newProject() {
  var name = el("newName").value.trim();
  if (!name) return;
  el("newRow").classList.add("hidden");
  el("newName").value = "";
  setBusy(true);
  setStatus("Creating " + name + "…");
  runDam(["new", name, "--no-launch"])
    .then(function () { return runDam(["list", "--json"]); })
    .then(function (out) {
      var projects = JSON.parse(out).projects;
      var created = projects.filter(function (p) { return p.name === name; })[0];
      if (!created) throw new Error("created, but could not find " + name + " afterwards");
      return evalScript('ODAM_openProject(' + JSON.stringify(created.path) + ')');
    })
    .then(function (result) {
      if (result !== "ok") throw new Error(result);
      setStatus(name + " created and opened.");
    })
    .catch(function (e) { setStatus(e.message, true); })
    .then(function () { setBusy(false); return refresh(true); });
}

/* ---------- boot ---------- */

document.addEventListener("DOMContentLoaded", function () {
  el("refresh").addEventListener("click", function () { refresh(false); });
  el("newProject").addEventListener("click", function () {
    el("newRow").classList.remove("hidden");
    el("newName").focus();
  });
  el("createNew").addEventListener("click", newProject);
  el("cancelNew").addEventListener("click", function () {
    el("newRow").classList.add("hidden");
    el("newName").value = "";
  });
  el("newName").addEventListener("keydown", function (e) {
    if (e.key === "Enter") newProject();
  });
  el("settings").addEventListener("click", function () { showSetup(""); });
  el("saveSettings").addEventListener("click", function () {
    saveSettingsValues(el("repoPath").value.trim(), el("damPath").value.trim());
    refresh(false);
  });

  var s = getSettings();
  var boot = s.damPath
    ? Promise.resolve()
    : detectDamPath().then(function (found) {
        if (found) localStorage.setItem("odam.damPath", found);
      });

  boot.then(function () {
    var ready = getSettings();
    if (!ready.repoPath || !ready.damPath) {
      showSetup("");
    } else {
      refresh(false);
    }
  });

  setInterval(function () {
    if (!state.busy && !el("main").classList.contains("hidden")) refresh(true);
  }, REFRESH_MS);
});
