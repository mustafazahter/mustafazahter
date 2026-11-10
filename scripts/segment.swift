import Foundation
import Vision
import CoreImage
import AppKit
let args = CommandLine.arguments
let inURL = URL(fileURLWithPath: args[1]); let outURL = URL(fileURLWithPath: args[2])
let ci = CIImage(contentsOf: inURL)!
let req = VNGeneratePersonSegmentationRequest()
req.qualityLevel = .accurate
req.outputPixelFormat = kCVPixelFormatType_OneComponent8
let h = VNImageRequestHandler(ciImage: ci, options: [:])
try! h.perform([req])
let buf = req.results!.first!.pixelBuffer
var mask = CIImage(cvPixelBuffer: buf)
let sx = ci.extent.width / mask.extent.width, sy = ci.extent.height / mask.extent.height
mask = mask.transformed(by: CGAffineTransform(scaleX: sx, y: sy))
let ctx = CIContext()
let cg = ctx.createCGImage(mask, from: ci.extent)!
let rep = NSBitmapImageRep(cgImage: cg)
try! rep.representation(using: .png, properties: [:])!.write(to: outURL)
print("ok")
