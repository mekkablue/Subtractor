# encoding: utf-8

###########################################################################################################
#
#
#	Filter with Dialog Plugin
#
#	Read the docs:
#	https://github.com/schriftgestalt/GlyphsSDK/tree/master/Python%20Templates/Filter%20with%20Dialog
#
#	For help on the use of Interface Builder:
#	https://github.com/schriftgestalt/GlyphsSDK/tree/master/Python%20Templates
#
#
###########################################################################################################

import objc
from GlyphsApp import *
from GlyphsApp.plugins import *
from Foundation import NSClassFromString, NSMutableArray
from math import cos, sin, radians
from random import choice, uniform


# Glyph names that are always excluded when running as a custom parameter
EXCLUDED_GLYPH_NAMES = frozenset(['.notdef', 'uniF8FF', 'apple'])


def getSubtractGlyphs(font, prefix='_subtract'):
	"""Return glyphs named exactly prefix or prefix.xxx from the font."""
	return [g for g in font.glyphs
			if g.name == prefix
			or g.name.startswith(prefix + '.')
			]


def getLayerCenter(layer):
	"""Compute bbox centre from node positions (works on detached layers)."""
	minX = minY = float('inf')
	maxX = maxY = float('-inf')
	for shape in layer.shapes:
		if isinstance(shape, GSPath):
			for node in shape.nodes:
				x, y = node.position.x, node.position.y
				if x < minX: minX = x
				if x > maxX: maxX = x
				if y < minY: minY = y
				if y > maxY: maxY = y
	if minX == float('inf'):
		return None
	return ((minX + maxX) / 2.0, (minY + maxY) / 2.0)


def applyTransformToLayer(layer, transform):
	"""Apply affine transform to each GSPath in layer individually."""
	for shape in layer.shapes:
		if isinstance(shape, GSPath):
			shape.applyTransform(transform)


def centerOnTarget(subtractCopy, targetLayer):
	"""Translate subtractCopy so its bbox centre aligns with targetLayer's bbox centre."""
	sc = getLayerCenter(subtractCopy)
	tc = getLayerCenter(targetLayer)
	if sc is None or tc is None:
		return
	dx = tc[0] - sc[0]
	dy = tc[1] - sc[1]
	applyTransformToLayer(subtractCopy, (1, 0, 0, 1, dx, dy))


def applyRandomTransform(layer, maxRotate, maxOffset):
	"""Randomly rotate (around bbox centre) and offset all shapes in layer."""
	center = getLayerCenter(layer)
	if center is None:
		return
	cx, cy = center
	angle = radians(uniform(-maxRotate, maxRotate))
	dx = uniform(-maxOffset, maxOffset)
	dy = uniform(-maxOffset, maxOffset)
	cosA = cos(angle)
	sinA = sin(angle)
	# Rotate around (cx, cy), then translate by (dx, dy)
	tX = cx * (1.0 - cosA) + cy * sinA + dx
	tY = cy * (1.0 - cosA) - cx * sinA + dy
	applyTransformToLayer(layer, (cosA, sinA, -sinA, cosA, tX, tY))


def subtractFromLayer(targetLayer, subtractLayer, maxRotate=0.0, maxOffset=0.0, centerBounds=False):
	"""
	Boolean-subtract subtractLayer's shapes from targetLayer.
	Mirrors the subtract=YES branch in Risorizer.m (processLayer:…subtract:).
	"""
	# 1. Clean target layer in place
	targetLayer.removeOverlap()

	# 2. Decomposed, cleaned copy of the subtract shapes
	subtractCopy = subtractLayer.copyDecomposedLayer()
	subtractCopy.removeOverlap()
	subtractCopy.correctPathDirection()

	# 3. Optionally centre subtract shape on target, then rotate and offset
	if centerBounds:
		centerOnTarget(subtractCopy, targetLayer)
	if maxRotate != 0.0 or maxOffset != 0.0:
		applyRandomTransform(subtractCopy, maxRotate, maxOffset)

	# 4. Boolean subtraction via GSPathOperator (same class used by Risorizer.m)
	subtrahends = NSMutableArray.arrayWithArray_(
		[s for s in subtractCopy.shapes if isinstance(s, GSPath)]
	)
	minuends = NSMutableArray.arrayWithArray_(
		[s for s in targetLayer.shapes if isinstance(s, GSPath)]
	)

	if not subtrahends or not minuends:
		return

	GSPathOperator = NSClassFromString("GSPathOperator")
	GSPathOperator.subtractPaths_from_error_(subtrahends, minuends, None)

	# 5. Put the result back and normalise directions
	targetLayer.shapes = minuends
	targetLayer.correctPathDirection()


def buildComponentTransform(subtractLayer, targetLayer, maxRotate, maxOffset, centerBounds):
	"""
	Return a 6-tuple affine transform (m11,m12,m21,m22,tX,tY) for a GSComponent
	so it gets the same centering, random rotation and random offset that
	subtractFromLayer would apply to the paths.

	Derivation: compose
	  1. centering translation  (tx-sx, ty-sy)  — only when centerBounds
	  2. rotation by θ around the pivot (cx,cy)  — (cx,cy) is the subtract
	     shape's centre after the optional centering step
	  3. random offset (rdx, rdy)
	into a single affine matrix applied to the component's local coordinates.
	"""
	sc = getLayerCenter(subtractLayer)
	if sc is None:
		return (1, 0, 0, 1, 0, 0)
	sx, sy = sc

	# Rotation pivot after the optional centering step
	if centerBounds:
		tc = getLayerCenter(targetLayer)
		cx, cy = tc if tc is not None else (sx, sy)
	else:
		cx, cy = sx, sy

	angle = radians(uniform(-maxRotate, maxRotate))
	rdx   = uniform(-maxOffset, maxOffset)
	rdy   = uniform(-maxOffset, maxOffset)
	cosA  = cos(angle)
	sinA  = sin(angle)

	# For a point (x,y) in the subtract glyph's own coordinate space:
	#   after centering:  (x + cx-sx,  y + cy-sy)
	#   after rotation around (cx,cy) and adding the random offset:
	#     x' = cosA*x - sinA*y + (cx - sx*cosA + sy*sinA + rdx)
	#     y' = sinA*x + cosA*y + (cy - sy*cosA - sx*sinA + rdy)
	tX = cx - sx * cosA + sy * sinA + rdx
	tY = cy - sy * cosA - sx * sinA + rdy
	return (cosA, sinA, -sinA, cosA, tX, tY)


class Subtractor(FilterWithDialog):

	# The NSView object from the User Interface. Keep this here!
	dialog = objc.IBOutlet()

	# Text fields and checkboxes in dialog
	subtractField          = objc.IBOutlet()
	rotateField            = objc.IBOutlet()
	offsetField            = objc.IBOutlet()
	centerBoundsField      = objc.IBOutlet()
	maskedComponentsField  = objc.IBOutlet()


	@objc.python_method
	def prefName(self, name):
		return "com.mekkablue.Subtractor." + name.strip()


	@objc.python_method
	def getPref(self, name):
		return Glyphs.defaults[self.prefName(name)]


	@objc.python_method
	def settings(self):
		self.menuName = Glyphs.localize({
			'en': 'Subtractor',
			'de': 'Abzieher',
			'fr': 'Soustracteur',
			'es': 'Sustractor',
		})
		self.actionButtonLabel = Glyphs.localize({
			'en': 'Subtract',
			'de': 'Abziehen',
			'fr': 'Soustraire',
			'es': 'Sustraer',
			'pt': 'Subtrair',
			'jp': '削除',
			'ko': '빼기',
			'zh': '减去',
		})
		# Load dialog from .nib (without .extension)
		self.loadNib('IBdialog', __file__)


	# On dialog show
	@objc.python_method
	def start(self):
		# Set default values
		Glyphs.registerDefault(self.prefName('subtractShapes'),    '_subtract')
		Glyphs.registerDefault(self.prefName('randomRotate'),      5.0)
		Glyphs.registerDefault(self.prefName('randomOffset'),      20.0)
		Glyphs.registerDefault(self.prefName('centerBounds'),      0)
		Glyphs.registerDefault(self.prefName('maskedComponents'),  0)

		# Populate fields
		self.subtractField.setStringValue_(self.getPref('subtractShapes'))
		self.rotateField.setStringValue_(self.getPref('randomRotate'))
		self.offsetField.setStringValue_(self.getPref('randomOffset'))
		self.centerBoundsField.setState_(int(self.getPref('centerBounds')))
		self.maskedComponentsField.setState_(int(self.getPref('maskedComponents')))

		# Focus first field
		self.subtractField.becomeFirstResponder()


	# Update prefs with user-entered values:
	@objc.IBAction
	def setSubtractShapes_(self, sender):
		Glyphs.defaults[self.prefName('subtractShapes')] = sender.stringValue()
		self.update()

	@objc.IBAction
	def setRandomRotate_(self, sender):
		Glyphs.defaults[self.prefName('randomRotate')] = sender.floatValue()
		self.update()

	@objc.IBAction
	def setRandomOffset_(self, sender):
		Glyphs.defaults[self.prefName('randomOffset')] = sender.floatValue()
		self.update()

	@objc.IBAction
	def setCenterBounds_(self, sender):
		Glyphs.defaults[self.prefName('centerBounds')] = sender.state()
		self.update()

	@objc.IBAction
	def setMaskedComponents_(self, sender):
		Glyphs.defaults[self.prefName('maskedComponents')] = sender.state()
		self.update()


	# Actual filter
	@objc.python_method
	def filter(self, layer, inEditView, customParameters):
		try:
			# avoid processing newlines in Edit view:
			if not isinstance(layer, GSLayer):
				return

			# skip empty layers
			if not layer.shapes:
				return

			glyphName = layer.parent.name

			# Defaults
			subtractShapes    = '_subtract'
			maxRotate         = 5.0
			maxOffset         = 20.0
			centerBounds      = False
			maskedComponents  = False  # Edit-view only; has no effect on custom parameter

			if not inEditView:
				# always skip predefined exclusions
				if glyphName in EXCLUDED_GLYPH_NAMES:
					return

				# Batch export via custom parameter — read settings and apply exclusions
				if 'subtractShapes' in customParameters:
					subtractShapes = str(customParameters['subtractShapes'])
				if 'randomRotate' in customParameters:
					maxRotate = float(customParameters['randomRotate'])
				if 'randomOffset' in customParameters:
					maxOffset = float(customParameters['randomOffset'])
				if 'centerBounds' in customParameters:
					centerBounds = bool(int(customParameters['centerBounds']))

				# do not subtract from subtract shapes
				if glyphName.startswith(subtractShapes):
					return
			else:
				# Interactive — read stored preferences
				try:
					subtractShapes = str(self.getPref('subtractShapes') or '_subtract')
				except:
					pass
				try:
					maxRotate = float(self.getPref('randomRotate'))
				except:
					pass
				try:
					maxOffset = float(self.getPref('randomOffset'))
				except:
					pass
				try:
					centerBounds = bool(int(self.getPref('centerBounds')))
				except:
					pass
				try:
					maskedComponents = bool(int(self.getPref('maskedComponents')))
				except:
					pass

			font = layer.parent.parent
			subtractGlyphs = getSubtractGlyphs(font, subtractShapes)

			if not subtractGlyphs:
				if inEditView:
					Message(
						"No subtract glyphs found.\n\n"
						"Please add a glyph named \u2018%s\u2019 "
						"(or \u2018%s.xxx\u2019 with a dot suffix) to your font." % (
							subtractShapes, subtractShapes),
						title="Subtractor"
					)
				return

			# Pick one subtract glyph at random
			subtractGlyph = choice(subtractGlyphs)
			subtractLayer = subtractGlyph.layers[layer.associatedMasterId]

			# Fall back to first layer if this master has no corresponding layer
			if subtractLayer is None and subtractGlyph.layers:
				subtractLayer = subtractGlyph.layers[0]

			if subtractLayer is None or not subtractLayer.shapes:
				return

			if maskedComponents:
				# Remove any pre-existing components whose glyph name matches the
				# subtract-shapes prefix before placing the new one, so there is
				# never more than one subtract component on the layer at a time.
				layer.shapes = [
					s for s in layer.shapes
					if not (
						isinstance(s, GSComponent)
						and (
							s.componentName == subtractShapes
							or s.componentName.startswith(subtractShapes + '.')
						)
					)
				]
				# Edit-view only: place a masked component instead of boolean-subtracting
				component = GSComponent(subtractGlyph.name)
				component.attributes['mask'] = 1
				if centerBounds or maxRotate != 0.0 or maxOffset != 0.0:
					component.transform = buildComponentTransform(
						subtractLayer, layer, maxRotate, maxOffset, centerBounds
					)
				layer.shapes.append(component)
			else:
				subtractFromLayer(layer, subtractLayer, maxRotate, maxOffset, centerBounds)

		except Exception as e:
			import traceback
			if inEditView:
				print("\nSubtractor Error:")
				print(traceback.format_exc())
				print(e)
			else:
				self.logToConsole("Subtractor Error: %s\n%s" % (str(e), traceback.format_exc()))


	@objc.python_method
	def generateCustomParameter(self):
		return "%s; subtractShapes:%s; randomRotate:%s; randomOffset:%s; centerBounds:%s" % (
			self.__class__.__name__,
			self.getPref('subtractShapes'),
			self.getPref('randomRotate'),
			self.getPref('randomOffset'),
			int(self.getPref('centerBounds')),
		)


	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
