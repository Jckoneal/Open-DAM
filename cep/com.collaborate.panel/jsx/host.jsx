// ExtendScript bridge for the Collaborate panel. Runs inside Premiere Pro's
// scripting engine, so it can do the things an external CLI can't: open a
// project, and save + close it programmatically before check-in.
//
// Every function returns a plain string ("ok" or "error: ...") because
// CEP's evalScript only transports strings.

function ODAM_openProject(path) {
    try {
        app.openDocument(path);
        return "ok";
    } catch (e) {
        return "error: " + e.toString();
    }
}

function ODAM_currentProjectPath() {
    try {
        if (app.project && app.project.path) {
            return String(app.project.path);
        }
        return "";
    } catch (e) {
        return "";
    }
}

function ODAM_saveProject() {
    try {
        if (!app.project) return "error: no project open";
        app.project.save();
        return "ok";
    } catch (e) {
        return "error: " + e.toString();
    }
}

function ODAM_saveAndCloseProject() {
    try {
        if (!app.project) return "error: no project open";
        app.project.save();
        // closeDocument's signature grew arguments over Premiere versions;
        // calling it bare works everywhere and we already saved explicitly.
        app.project.closeDocument();
        return "ok";
    } catch (e) {
        return "error: " + e.toString();
    }
}
