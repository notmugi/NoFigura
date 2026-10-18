#!/usr/bin/env python3
"""python3 tests/check_toggle_init.py (JDK 25; JAVA25_HOME overrides default).

Real cached Figura LuaJ core+jse, extracted runtime registration/stack lookup,
Action registration/state setters and Animation capture/play/stop/gate methods.
Lua models actionHelper.lua v0.3 toggle verbatim (apart from comments); Java
userdata/VarArgFunction bridges replace Figura's reflection wrappers. No hooks,
callback replay, Minecraft, network, renderer or instruction limiter is modeled.
Sources/classes live temporarily under tests/.work, never /tmp. No downloads.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from check_wheel_animations import ROOT, SOURCE, JDK, block


# actionHelper.lua v0.3, as installed in the avatar's Addons/Requires directory.
# Keep its closure nesting, ping setup, direct initialization and setter order.
HELPER = r'''
local actionHelper = {}
function actionHelper.toggle(page, name, func, pickyInit, defaultState, prePing)
    local obj = {
        action = page:newAction()
            :setTitle("Enable " .. name)
            :setToggleTitle("Disable " .. name),
        func = func,
        preping = prePing,
        state = config:load(name) or false,
    }
    pings[name] = function(state)
        obj.func(state, true)
    end
    obj.ping = pings[name]
    local function actionFunc(state, action, noping)
        if prePing then
            if not prePing() then
                obj.action:setToggled(obj.state)
                return
            end
        end
        obj.state = state
        if obj.func then
            if noping or not obj.ping then
                obj.func(state)
            end
            if obj.ping then
                if not noping then
                    obj.ping(state)
                end
            end
        end
        obj.action:setToggled(obj.state)
        config:save(name,obj.state)
    end
    obj.action:setOnToggle(actionFunc)
    if not pickyInit or config:load(name) then
        local initState = config:load(name)
        if initState == nil then
            initState = defaultState
        end
        actionFunc(initState, obj.action, true)
    end
    return obj
end
'''

CHECKS = r'''
local saved = {umbrella = true, second = false}
local saves, calls, rain = 0, 0, false
config = {
    load = function(_, name) return saved[name] end,
    save = function(_, name, state) saves = saves + 1; saved[name] = state end,
}
pings = {}

-- Verify the real debug.getinfo 'f' API identifies closure instances, not prototypes.
local function factory()
    local function f() assert(debug.getinfo(1, "f").func == f) end
    return f
end
local f, g = factory(), factory()
assert(f ~= g)
f(); g()
-- Production calls getinfo directly from Java, not via a Lua debug.getinfo call.
-- Java wrappers add no DebugLib frame: level 1 is the immediate Lua caller.
local function indexCheck() probeIndex(indexCheck) end
indexCheck()

local umbrella, second, unrelated = clip(), clip(), clip()
local function weather(animation, enabled)
    animation:setPlaying(enabled and rain)
end
local function makeCallback(animation)
    return function(state)
        calls = calls + 1
        weather(animation, state)
        -- actionHelper has registered the closure but has NOT setToggled yet.
        local action = latestAction()
        assertOwner(animation, action)
        assert(not action:isToggled())
        assert(not animation:allowsBodyPose())
        assert(not animation:isPlaying())
    end
end
local one = actionHelper.toggle(page, "umbrella", makeCallback(umbrella))
assert(one.state and one.action:isToggled())
assertOwner(umbrella, one.action)
assert(umbrella:allowsBodyPose() and not umbrella:isPlaying())
assert(calls == 1 and saves == 1, "registration/lookup must not replay callbacks")

local two = actionHelper.toggle(page, "second", makeCallback(second))
assert(not two.state and not two.action:isToggled())
assertOwner(second, two.action)
assertOwner(umbrella, one.action)
assert(not second:allowsBodyPose())
assertDistinctCallbacks(one.action, two.action) -- same Lua prototype, distinct identity
assert(calls == 2 and saves == 2)

-- No clicks: later ordinary weather ticks retain ownership, but gain none.
local function tick()
    weather(umbrella, one.state)
    weather(second, two.state)
    weather(unrelated, true)
end
rain = true
tick()
assert(umbrella:isPlaying() and umbrella:allowsBodyPose())
assert(not second:isPlaying() and not second:allowsBodyPose())
assert(unrelated:isPlaying() and not unrelated:allowsBodyPose())
assertOwner(unrelated, nil)
assertOwner(second, two.action)
rain = false; tick()
assert(not umbrella:isPlaying() and umbrella:allowsBodyPose())
rain = true; tick()
assert(umbrella:isPlaying() and umbrella:allowsBodyPose())
one.action:setToggled(false)
assert(not umbrella:allowsBodyPose())
two.action:setToggled(true)
assert(second:allowsBodyPose() and not umbrella:allowsBodyPose())
assert(calls == 2 and saves == 2, "ticks and setters must not replay callbacks")

-- Bypass actionFunc and call the same obj.func closure directly: no attribution.
local directClip = clip()
local directCalls = 0
local skipped = actionHelper.toggle(page, "skipped", function(state)
    directCalls = directCalls + 1
    weather(directClip, state)
end, true)
assert(directCalls == 0)
skipped.func(true)
assertOwner(directClip, nil)
assert(not directClip:allowsBodyPose() and directCalls == 1)

-- Nearest registered closure wins; nested errors unwind the real Lua call stack.
local outerAction, innerAction = page:newAction(), page:newAction()
local outerClip, innerClip, afterClip = clip(), clip(), clip()
local outerCalls, innerCalls = 0, 0
local function deepest(animation) animation:stop() end
local function middle(animation) deepest(animation) end
local function inner()
    innerCalls = innerCalls + 1
    middle(innerClip)
    assertOwner(innerClip, innerAction)
    error("expected nested error")
end
local function outer()
    outerCalls = outerCalls + 1
    middle(outerClip)
    assertOwner(outerClip, outerAction)
    local ok, err = pcall(inner)
    assert(not ok and string.find(err, "expected nested error", 1, true))
    middle(afterClip)
    assertOwner(afterClip, outerAction)
end
outerAction:setOnToggle(outer)
innerAction:setOnToggle(inner)
assert(outerCalls == 0 and innerCalls == 0)
outer()
assert(outerCalls == 1 and innerCalls == 1)
local fresh = clip(); middle(fresh); assertOwner(fresh, nil)
local ok = pcall(inner)
assert(not ok and innerCalls == 2)
local freshAfterError = clip(); freshAfterError:setPlaying(false)
assertOwner(freshAfterError, nil)
assertNoInitializingToggle()

-- Immediate Lua caller at the bridge boundary, replacement and unregistering.
local replaceAction, replacedClip = page:newAction(), clip()
local function old() replacedClip:setPlaying(false) end
local function replacement() replacedClip:setPlaying(false) end
replaceAction:setOnToggle(old)
replaceAction:setOnToggle(replacement)
old(); assertOwner(replacedClip, nil)
replacement(); assertOwner(replacedClip, replaceAction)
replaceAction:setOnToggle(nil)
local unregistered = clip()
replacedClip = unregistered
replacement(); assertOwner(unregistered, nil)

-- One actual closure shared by two Actions is ambiguous: never guess an owner.
local sharedClip = clip()
local function shared() sharedClip:setPlaying(false) end
local sharedA, sharedB = page:newAction(), page:newAction()
sharedA:setOnToggle(shared); sharedB:setOnToggle(shared)
shared(); assertOwner(sharedClip, nil)
assert(not sharedClip:allowsBodyPose())
assert(calls == 2 and saves == 2 and directCalls == 1)
assertNoInitializingToggle()
'''

JAVA = r'''
import java.util.*;
import org.luaj.vm2.*;
import org.luaj.vm2.compiler.LuaC;
import org.luaj.vm2.lib.*;
import org.luaj.vm2.lib.jse.*;

class Avatar {
    boolean actionWheelCallback;
    Action actionWheelToggle;
    FiguraLuaRuntime luaRuntime;
    boolean followsVanillaPose() { return true; }
}
class TimeController {
    void init() {} void reset() {} void resume() {}
}
class FiguraLuaRuntime {
    final Globals userGlobals = new Globals();
    final LuaFunction getInfoFunction;
    FiguraLuaRuntime() {
        userGlobals.load(new JseBaseLib());
        userGlobals.load(new Bit32Lib());
        userGlobals.load(new TableLib());
        userGlobals.load(new JseStringLib());
        userGlobals.load(new JseMathLib());
        LuaC.install(userGlobals);
        userGlobals.load(new DebugLib());
        getInfoFunction = userGlobals.get("debug").get("getinfo").checkfunction();
    }
    @RUNTIME@
}
class Action {
    private final Avatar owner;
    boolean toggled;
    LuaFunction toggle, untoggle;
    @ACTION@
}
class Animation {
    private final Avatar owner;
    final String modelName, name;
    final TimeController controller = new TimeController();
    boolean inverted, actionWheelPlayback;
    Action actionWheelToggle;
    PlayState playState = PlayState.STOPPED;
    float length, offset, blend, startDelay, loopDelay, time, lastTime, frameTime;
    int override;
    LoopMode loop;
    @ANIMATION@
}
public class ToggleInitCheck {
    static final Avatar avatar = new Avatar();
    static final List<Action> actions = new ArrayList<>();
    static final LuaTable actionMethods = new LuaTable(), clipMethods = new LuaTable();
    static void require(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    static LuaUserdata wrap(Object object, LuaTable methods) {
        LuaTable meta = new LuaTable(); meta.set("__index", methods);
        return new LuaUserdata(object, meta);
    }
    static Action action(Varargs args) { return (Action) args.checkuserdata(1, Action.class); }
    static Animation clip(Varargs args) { return (Animation) args.checkuserdata(1, Animation.class); }
    static void bridges(Globals globals) {
        // Same VarArgFunction.invoke boundary used by LuaTypeManager.getWrapper.
        actionMethods.set("setOnToggle", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                action(args).setOnToggle(args.isnil(2) ? null : args.checkfunction(2));
                return args.arg1();
            }
        });
        actionMethods.set("setToggled", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                action(args).setToggled(args.checkboolean(2)); return args.arg1();
            }
        });
        actionMethods.set("isToggled", new VarArgFunction() {
            public Varargs invoke(Varargs args) { return LuaValue.valueOf(action(args).isToggled()); }
        });
        VarArgFunction title = new VarArgFunction() {
            public Varargs invoke(Varargs args) { return args.arg1(); }
        };
        actionMethods.set("setTitle", title); actionMethods.set("setToggleTitle", title);
        clipMethods.set("setPlaying", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                clip(args).setPlaying(args.checkboolean(2)); return args.arg1();
            }
        });
        clipMethods.set("stop", new VarArgFunction() {
            public Varargs invoke(Varargs args) { clip(args).stop(); return args.arg1(); }
        });
        clipMethods.set("allowsBodyPose", new VarArgFunction() {
            public Varargs invoke(Varargs args) { return LuaValue.valueOf(clip(args).allowsBodyPose()); }
        });
        clipMethods.set("isPlaying", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                return LuaValue.valueOf(clip(args).playState == Animation.PlayState.PLAYING);
            }
        });
        LuaTable page = new LuaTable();
        page.set("newAction", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                Action a = new Action(avatar); actions.add(a); return wrap(a, actionMethods);
            }
        });
        globals.set("page", page);
        globals.set("clip", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                return wrap(new Animation(avatar, "model", "clip", Animation.LoopMode.LOOP,
                        false, 100, 0, 1, 0, 0), clipMethods);
            }
        });
        globals.set("latestAction", new VarArgFunction() {
            public Varargs invoke(Varargs args) { return wrap(actions.getLast(), actionMethods); }
        });
        globals.set("assertOwner", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                Object expected = args.isnil(2) ? null : args.checkuserdata(2, Action.class);
                require(clip(args).actionWheelToggle == expected, "incorrect captured Action identity");
                require(!avatar.actionWheelCallback && avatar.actionWheelToggle == null,
                        "initialization must not rely on click scope");
                return LuaValue.NONE;
            }
        });
        globals.set("assertDistinctCallbacks", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                LuaClosure a = action(args).toggle.checkclosure();
                LuaClosure b = ((Action) args.checkuserdata(2, Action.class)).toggle.checkclosure();
                require(a != b && a.p == b.p, "fixture needs distinct closures of same prototype");
                return LuaValue.NONE;
            }
        });
        globals.set("probeIndex", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                LuaFunction info = avatar.luaRuntime.getInfoFunction;
                require(info.call(LuaValue.valueOf(0), LuaValue.valueOf("f")).isnil(),
                        "direct Java getinfo call must not add a Lua frame");
                require(info.call(LuaValue.valueOf(1), LuaValue.valueOf("f")).get("func") == args.arg1(),
                        "Java lookup level 1 must include immediate Lua caller");
                require(info.call(LuaValue.valueOf(2), LuaValue.valueOf("f")).get("func").isclosure(),
                        "Java lookup level 2 must reach the enclosing Lua chunk");
                return LuaValue.NONE;
            }
        });
        globals.set("assertNoInitializingToggle", new VarArgFunction() {
            public Varargs invoke(Varargs args) {
                require(avatar.luaRuntime.findInitializingToggle() == null, "stale stack attribution");
                return LuaValue.NONE;
            }
        });
    }
    public static void main(String[] args) throws Exception {
        avatar.luaRuntime = new FiguraLuaRuntime();
        Globals globals = avatar.luaRuntime.userGlobals;
        bridges(globals);
        globals.load(java.nio.file.Files.readString(java.nio.file.Path.of(args[0])), "toggle-init").call();
        require(avatar.luaRuntime.findInitializingToggle() == null, "stack must unwind after chunk");
        System.out.println("PASS: real Figura LuaJ debug.getinfo(f) stack indices; actionHelper saved-state " +
                "false playback captures exact Action before setToggled; rain without clicks; " +
                "closure identity, unrelated ticks, nesting/errors, replacement/shared callbacks, no replay");
    }
}
'''


def main():
    version = re.search(r"^luaj\s*=\s*(\S+)", (ROOT / "gradle.properties").read_text(), re.M).group(1)
    cache = Path(os.environ.get("GRADLE_USER_HOME", Path.home() / ".gradle")) / "caches/modules-2/files-2.1"
    jars = []
    for artifact in ("luaj-core", "luaj-jse"):
        matches = sorted((cache / "com.github.FiguraMC.luaj" / artifact / (version + "-figura"))
                         .glob(f"*/{artifact}-{version}-figura.jar"))
        assert matches, f"Missing cached {artifact} {version}-figura jar (no downloads performed)"
        jars.append(str(matches[0]))
    runtime = (SOURCE / "lua/FiguraLuaRuntime.java").read_text()
    action = (SOURCE / "lua/api/action_wheel/Action.java").read_text()
    animation = (SOURCE / "animation/Animation.java").read_text()
    fields = re.findall(r"^    private final java.util.IdentityHashMap<LuaFunction, Action> actionToggles[^\n]+;", runtime, re.M)
    assert len(fields) == 1, "runtime registration storage changed"
    runtime_methods = fields[0] + "\n" + "\n".join(block(runtime, signature) for signature in (
        r"public void registerActionToggle\(Action action, LuaFunction previous, LuaFunction next\)",
        r"public Action findInitializingToggle\(\)",
    ))
    # These methods must only inspect the stack: never install hooks or invoke callbacks.
    assert not re.search(r"sethook|setHook|onCall|onReturn|DebugLib", runtime_methods)
    action_methods = "\n".join(block(action, signature) for signature in (
        r"public Action\(Avatar owner\)",
        r"private void registerToggle\(LuaFunction previous, LuaFunction next\)",
        r"public Action setOnToggle\(LuaFunction function\)",
        r"public Action setToggled\(boolean bool\)",
        r"public boolean isToggled\(\)",
    ))
    animation_methods = "\n".join(block(animation, signature) for signature in (
        r"private void captureToggleOwner\(\)", r"public boolean allowsBodyPose\(\)",
        r"public Animation\(Avatar owner,[^\n]+\)",
        r"public Animation play\(\)", r"public Animation stop\(\)",
        r"public Animation setPlaying\(boolean bool\)",
        r"public enum PlayState", r"public enum LoopMode",
    ))
    source = (JAVA.replace("@RUNTIME@", runtime_methods).replace("@ACTION@", action_methods)
              .replace("@ANIMATION@", animation_methods)
              .replace("org.figuramc.figura.lua.api.action_wheel.Action", "Action"))
    work = ROOT / "tests/.work"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="toggle-init-", dir=work) as directory:
        java = Path(directory) / "ToggleInitCheck.java"
        lua = Path(directory) / "toggle-init.lua"
        java.write_text(source)
        lua.write_text(HELPER + CHECKS)
        classpath = os.pathsep.join([directory, *jars])
        subprocess.run([str(JDK / "javac"), "--release", "25", "-cp", classpath,
                        "-d", directory, str(java)], check=True)
        subprocess.run([str(JDK / "java"), "-cp", classpath, "ToggleInitCheck", str(lua)], check=True)


if __name__ == "__main__":
    main()
