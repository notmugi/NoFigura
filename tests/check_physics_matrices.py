#!/usr/bin/env python3
"""Run with python3 tests/check_physics_matrices.py (JDK25 + existing build).

Extracts Avatar.render and production renderer traversal. Real compiled model
parts, customizations, matrix math, and Lua closures exercise a synthetic spring
(no private avatar fixture). Profiler, Avatar dispatch, and submission dependencies
are stubbed; empty faces execute real pushVerticesImmediate without a GPU.
No Minecraft session, vanilla model provider, mixin ordering, or GPU is simulated.
JAVA25_HOME, MINECRAFT_JAR and MINECRAFT_LIBRARIES override local dependencies.
All generated files live temporarily under tests/.work.
"""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'common/src/main/java/org/figuramc/figura'
JDK = Path(os.environ.get('JAVA25_HOME', '/usr/lib/jvm/java-25-openjdk')) / 'bin'


def between(source, start, end):
    assert source.count(start) == 1 and source.count(end) == 1, (start, end)
    return source[source.index(start):source.index(end)]


def main():
    renderer = (SOURCE / 'model/rendering/ImmediateFiguraRenderer.java').read_text()
    avatar = (SOURCE / 'avatar/Avatar.java').read_text()
    entry = between(avatar, '    public void render(Entity entity,',
                    '    public synchronized void worldRender(')
    traversal = between(renderer, '    private VanillaPose vanillaPose(',
                        '    protected boolean getPartComplexity(')
    # Only extras/debug rendering are replaced by a composed-matrix observation.
    start = traversal.index('        // render extras')
    end = traversal.index('        // render children', start)
    traversal = traversal[:start] + '''
        if (thisPassedPredicate) observed.put(part, customizationStack.peek().positionMatrix.copy());
''' + traversal[end:]
    assert traversal.count('part.pushVerticesImmediate(this, remainingComplexity)') == 1
    traversal = traversal.replace('part.pushVerticesImmediate(this, remainingComplexity)',
                                  'part.pushVerticesImmediate(null, remainingComplexity)')
    world = between(renderer, '    protected FiguraMat4 partToWorldMatrices(',
                    '    protected void calculatePartMatrices(')
    java = '''
import java.util.*;
import net.minecraft.client.Minecraft;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.LightLayer;
import net.minecraft.util.LightCoordsUtil;
import org.figuramc.figura.FiguraMod;
import org.figuramc.figura.model.*;
import org.figuramc.figura.model.rendering.*;
import org.figuramc.figura.math.matrix.*;
import org.figuramc.figura.math.vector.*;
import org.luaj.vm2.*;
import org.luaj.vm2.lib.*;
import org.luaj.vm2.lib.jse.JsePlatform;

class Traversal {
 final PartCustomization.PartCustomizationStack customizationStack = new PartCustomization.PartCustomizationStack();
 static final FiguraMat4 CAMERA_POS_TO_WORLD_MATRIX = FiguraMat4.of().translate(3, 0, 0);
 static final PartCustomization pivotOffsetter = new PartCustomization();
 final CallbackAvatar avatar = new CallbackAvatar();
 PartFilterScheme currentFilterScheme = PartFilterScheme.MODEL;
 VanillaModelData vanillaModelData = null;
 boolean ignoreVanillaVisibility=false, allowHiddenTransforms=true, allowMatrixUpdate=false, updateLight=false;
 float tickDelta;
 Map<FiguraModelPart, FiguraMat4> observed = new IdentityHashMap<>();
 static class CallbackAvatar {
  boolean follow, combatPose, combatFirstPerson;
  Object render;
  EntityRenderMode renderMode = EntityRenderMode.RENDER;
  int calls;
  boolean followsVanillaPose() { return follow; }
  void run(LuaFunction f, Object ignored, Object... args) {
   calls++;
   f.call(LuaValue.valueOf(((Number)args[0]).doubleValue()), LuaValue.valueOf(args[1].toString()));
  }
 }
 void frame(FiguraModelPart root, double x) {
  observed.clear();
  PartCustomization outer = new PartCustomization();
  outer.positionMatrix.scale(1/16d, 1/16d, 1/16d).rotateZ(180).translate(x, 1.5, 0);
  customizationStack.push(outer);
  renderPart(root, new int[]{100000}, true);
  customizationStack.pop();
  PhysicsCheck.require(customizationStack.isEmpty(), "customization stack leak");
 }
''' + traversal + world + '''
}

// Dependency stubs around the *unaltered* production Avatar.render entry point.
class Entry {
 static class Entity {}
 static class PoseStack {}
 static class SubmitNodeCollector {}
 static class EntityModel<T> {}
 final Traversal traversal;
 Renderer renderer = new Renderer();
 boolean loaded = true;
 EntityRenderMode renderMode = EntityRenderMode.RENDER;
 FiguraModelPart root;
 double x;
 int submissions;
 boolean expectedFlag;
 Entry(Traversal traversal) { this.traversal = traversal; }
 class Renderer {
  boolean allowMatrixUpdate;
  float yaw;
  Entity entity;
  Data vanillaModelData = new Data();
  class Data {
   void update(EntityModel<?> ignored) {
    PhysicsCheck.require(allowMatrixUpdate == expectedFlag, "flag must be correct BEFORE vanillaModelData.update: " + renderMode);
   }
  }
  void setupRenderer(PartFilterScheme filter, SubmitNodeCollector collector, PoseStack stack,
                     float delta, int light, float alpha, int overlay,
                     boolean translucent, boolean glowing, int outlineColor) {}
 }
 PoseStack playerPoseStack(EntityModel<?> model, PoseStack stack) { return stack; }
 void render() {
  submissions++;
  if (root != null) {
   traversal.allowMatrixUpdate = renderer.allowMatrixUpdate;
   traversal.avatar.renderMode = renderMode;
   traversal.frame(root, x);
  }
 }
 void submit() { render(null, 0, 0.5f, 1, new PoseStack(), null, 0, 0, null, PartFilterScheme.MODEL, false, false, 0); }
''' + entry + '''
}

public class PhysicsCheck {
 static void require(boolean value, String message) {
  if (!value) throw new AssertionError(message);
 }
 static FiguraModelPart part(String name) {
  FiguraModelPart p = new FiguraModelPart(null, name, new PartCustomization(), new HashMap<>(), new ArrayList<>());
  p.facesByTexture = List.of();
  return p;
 }
 static void combatVisibility(boolean follow) {
  Traversal t = new Traversal(); t.avatar.follow = follow; t.avatar.combatPose = true;
  t.vanillaModelData = new VanillaModelData();
  for (VanillaModelData.PartData pose : t.vanillaModelData.partMap.values()) {
   pose.scale.set(1, 1, 1); pose.visible = true;
  }
  t.vanillaModelData.partMap.get(ParentType.LeftArm).rot.set(0, 0, 60);
  t.vanillaModelData.partMap.get(ParentType.RightArm).rot.set(0, 0, -60);
  FiguraModelPart root = part("combatRoot");
  List<FiguraModelPart> hidden = new ArrayList<>(), retained = new ArrayList<>();
  for (ParentType type : List.of(ParentType.Head, ParentType.Body, ParentType.LeftLeg,
                                 ParentType.RightLeg, ParentType.LeftArm, ParentType.RightArm)) {
   FiguraModelPart bone = part(type.name());
   bone.parentType = bone.bindParentType = type;
   bone.animationOverride = 7;
   bone.customization.setAnimPos(3, 4, 5);
   bone.customization.setAnimRot(6, 7, 8);
   bone.customization.setAnimScale(9, 10, 11);
   root.children.add(bone); bone.parent = root;
   if (type == ParentType.LeftArm || type == ParentType.RightArm) {
    retained.add(bone);
    FiguraModelPart pivot = part(type + "ItemPivot");
    pivot.parentType = pivot.bindParentType = type == ParentType.LeftArm
      ? ParentType.LeftItemPivot : ParentType.RightItemPivot;
    bone.children.add(pivot); pivot.parent = bone;
    pivot.markVanillaPoseParts(); retained.add(pivot);
   } else hidden.add(bone);
   bone.markVanillaPoseParts();
  }
  FiguraModelPart accessory = part("armAccessory");
  FiguraModelPart arm = retained.getFirst();
  arm.children.add(accessory); accessory.parent = arm;
  accessory.markVanillaPoseParts(); retained.add(accessory);
  // Valid nested rig: hiding Body must not prune its arms or held-item pivots.
  FiguraModelPart body = hidden.get(1);
  for (FiguraModelPart bone : new ArrayList<>(root.children)) {
   if (bone.bindParentType == ParentType.LeftArm || bone.bindParentType == ParentType.RightArm) {
    root.children.remove(bone); body.children.add(bone); bone.parent = body;
   }
  }
  body.markVanillaPoseParts();
  root.markVanillaPoseParts();
  require(!accessory.vanillaPosePart, "accessory incorrectly classified as body rig");
  int[] callbacks = {0, 0, 0};
  accessory.preRender = new ZeroArgFunction() {
   public LuaValue call() { callbacks[0]++; return NIL; }
  };
  accessory.midRender = new ZeroArgFunction() {
   public LuaValue call() { callbacks[1]++; return NIL; }
  };
  accessory.postRender = new ZeroArgFunction() {
   public LuaValue call() { callbacks[2]++; return NIL; }
  };
  List<FiguraModelPart> all = new ArrayList<>(hidden); all.addAll(retained); all.add(root);
  Map<FiguraModelPart, PartCustomization> live = new IdentityHashMap<>();
  for (FiguraModelPart p : all) live.put(p, p.customization);
  // Same rig, consecutive camera passes: hiding must never persist in live state.
  for (boolean firstPerson : new boolean[]{true, false}) {
   t.avatar.combatFirstPerson = firstPerson;
   t.frame(root, 0);
   for (FiguraModelPart p : hidden)
    require(t.observed.containsKey(p) != firstPerson, "combat visibility: " + p.name);
   for (FiguraModelPart p : retained) {
    if (p.bindParentType == ParentType.LeftArm || p.bindParentType == ParentType.RightArm)
     require(Math.abs(t.observed.get(p).v12) > 0.01,
             "PAL arm rotation lost to Figura override/idle channels: " + p.name);
   }
   for (FiguraModelPart p : retained)
    require(t.observed.containsKey(p), "combat dropped arm/pivot/accessory: " + p.name);
   for (FiguraModelPart p : all) {
    require(p.customization == live.get(p) && p.customization.visible,
            "combat leaked customization/visibility: " + p.name);
    require(p.parentType == p.bindParentType, "combat leaked parent type: " + p.name);
    if (p.bindParentType.provider != null) {
     require(p.animationOverride == 7, "combat leaked animation override");
     require(p.customization.getAnimPos().equals(FiguraVec3.of(3, 4, 5)) &&
             p.customization.getAnimRot().equals(FiguraVec3.of(6, 7, 8)) &&
             p.customization.getAnimScale().equals(FiguraVec3.of(9, 10, 11)),
             "combat leaked animation channels");
    }
   }
   for (int count : callbacks)
    require(count == (firstPerson ? 1 : 2), "combat accessory callback skipped/duplicated");
  }
 }
 public static void main(String[] args) {
  for (boolean follow : new boolean[]{false, true}) {
   Traversal t = new Traversal(); t.avatar.follow = follow;
   Entry e = new Entry(t);
   // Exercise every mode, both stale false and already true; only RENDER promotes.
   for (EntityRenderMode mode : EntityRenderMode.values()) {
    for (boolean initial : new boolean[]{false, true}) {
     e.renderMode = mode;
     e.renderer.allowMatrixUpdate = initial;
     e.expectedFlag = initial || mode == EntityRenderMode.RENDER;
     e.submit();
     require(e.renderer.allowMatrixUpdate == e.expectedFlag, "mode changed matrix flag: " + mode);
    }
   }
   int submitted = e.submissions;
   e.loaded = false; e.renderer.allowMatrixUpdate = false; e.renderMode = EntityRenderMode.RENDER;
   e.submit();
   require(!e.renderer.allowMatrixUpdate && e.submissions == submitted, "unloaded guard");
   e.loaded = true;
   Entry.Renderer savedRenderer = e.renderer; e.renderer = null; e.submit(); e.renderer = savedRenderer;
   require(e.submissions == submitted, "null renderer guard");

   FiguraModelPart root = part("syntheticSpringRoot"), child = part("syntheticSpringChild");
   root.children.add(child); child.parent = root;
   root.customization.setPivot(FiguraVec3.of(2, 3, 0));
   child.markVanillaPoseParts(); root.markVanillaPoseParts();
   require(!root.vanillaPosePart && !child.vanillaPosePart, "synthetic physics must remain script controlled");
   e.root = root;
   Globals lua = JsePlatform.standardGlobals();
   int[] reads = {0}, writes = {0};
   lua.set("worldX", new ZeroArgFunction() {
    public LuaValue call() {
     // Assert *inside* midRender: an after-traversal assertion misses ordering bugs.
     FiguraMat4 expected = t.customizationStack.peek().positionMatrix.copy()
       .multiply(Traversal.CAMERA_POS_TO_WORLD_MATRIX)
       .rightMultiply(FiguraMat4.of().translate(root.customization.getPivot()));
     require(expected.equals(root.savedPartToWorldMat), "stale saved world matrix before midRender");
     require(expected.equals(root.partToWorldMatrix()), "Lua world getter differs from saved matrix");
     reads[0]++;
     return LuaValue.valueOf(root.partToWorldMatrix().apply(0d, 0d, 0d).x);
    }
   });
   lua.set("setChildMatrix", new OneArgFunction() {
    public LuaValue call(LuaValue x) {
     child.setMatrix(FiguraMat4.of().translate(x.checkdouble(), 2, 0));
     writes[0]++;
     return NIL;
    }
   });
   // Minimal spring: real Lua state/closure, native world getter and model setMatrix.
   root.midRender = lua.load("""
    local last, displacement = nil, 0
    return function(delta, mode)
      assert(mode == 'RENDER')
      local x = worldX()
      if last then displacement = displacement * 0.65 + (last - x) * 8 end
      last = x
      setChildMatrix(displacement)
    end
    """).call().checkfunction();
   FiguraMat4 previousLocal = null, previousDraw = null;
   int localChanges = 0, drawChanges = 0;
   for (int frame = 0; frame < 40; frame++) {
    // Simulate preceding hand/preview passes disabling updates on every frame.
    e.renderer.allowMatrixUpdate = false;
    root.savedPartToWorldMat.reset().translate(-999, -999, -999);
    e.expectedFlag = true;
    e.x = Math.sin(frame * 0.17);
    e.submit();
    require(reads[0] == frame + 1 && writes[0] == frame + 1, "midRender/write skipped or duplicated");
    FiguraMat4 actual = t.observed.get(child);
    FiguraMat4 local = child.customization.positionMatrix;
    FiguraMat4 expected = local.copy().multiply(t.observed.get(root));
    require(actual.equals(expected), "child setMatrix not composed in the same frame");
    FiguraVec3 position = actual.apply(0d, 0d, 0d);
    require(Double.isFinite(position.x) && Double.isFinite(position.y) && Double.isFinite(position.z), "nonfinite physics");
    if (previousLocal != null && !previousLocal.equals(local)) localChanges++;
    if (previousDraw != null && !previousDraw.equals(actual)) drawChanges++;
    previousLocal = local.copy(); previousDraw = actual.copy();
   }
   require(localChanges > 30 && drawChanges > 30 && t.avatar.calls == 40, "physics frozen or callbacks missing");
   combatVisibility(follow);
   System.out.println("PASS follow=" + follow + ": mode gate, fresh pre-midRender world matrix, moving spring, same-frame child composition; " +
     "combat first-person hides head/body/legs, retains arms/pivots/accessory callbacks; third-person visibility restored");
  }
 }
}
'''
    classes = ROOT / 'common/build/classes/java/main'
    minecraft = Path(os.environ.get('MINECRAFT_JAR', str(Path.home() / '.gradle/caches/fabric-loom/26.2/minecraft-merged.jar')))
    libraries = Path(os.environ.get('MINECRAFT_LIBRARIES', str(Path.home() / '.local/share/PrismLauncher/libraries')))
    luaj = [ROOT / f'fabric/build/processIncludeJars/luaj-{kind}-3.0.8-figura.jar' for kind in ('core', 'jse')]
    for dependency in [classes / 'org/figuramc/figura/model/FiguraModelPart.class', minecraft, *luaj, JDK / 'javac']:
        if not dependency.exists():
            raise SystemExit(f'Missing existing build dependency: {dependency}; build the project first.')
    jars = sorted(libraries.rglob('*.jar'))
    assert jars, f'No Minecraft dependency jars under {libraries}'
    cp = os.pathsep.join(map(str, [classes, *luaj, minecraft, *jars]))
    work = ROOT / 'tests/.work'
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work, prefix='physics-matrices-') as directory:
        temp = Path(directory)
        source = temp / 'PhysicsCheck.java'
        source.write_text(java)
        profiler = temp / 'org/figuramc/figura/FiguraMod.java'
        profiler.parent.mkdir(parents=True)
        profiler.write_text('''package org.figuramc.figura;
public class FiguraMod {
 public static void pushProfiler(String s) {}
 public static void popPushProfiler(String s) {}
 public static void popProfiler() {}
 public static void popProfiler(int n) {}
}
''')
        env = dict(os.environ, TMPDIR=directory, TMP=directory, TEMP=directory)
        subprocess.run([str(JDK / 'javac'), f'-J-Djava.io.tmpdir={directory}', '-cp', cp,
                        '-d', directory, str(source), str(profiler)], check=True, env=env, cwd=temp)
        subprocess.run([str(JDK / 'java'), f'-Djava.io.tmpdir={directory}', '-cp',
                        directory + os.pathsep + cp, 'PhysicsCheck'], check=True, env=env, cwd=temp)


if __name__ == '__main__':
    main()
