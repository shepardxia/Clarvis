#!/usr/bin/env swift
// Standalone ASR test — run from ClarvisWidget/ directory:
//   swiftc -O -o test_asr test_asr.swift -framework Foundation -framework Speech -framework AVFoundation
//   ./test_asr [analyzer|recognizer]
//
// "analyzer"   — SpeechAnalyzer (macOS 26+ async API) with converter
// "recognizer" — SFSpeechRecognizer (proven callback API, no converter needed)
//
// Captures 8 seconds of mic audio. Speak clearly after "Listening..."

import Foundation
import Speech
import AVFoundation

// MARK: - Test 1: SpeechAnalyzer (macOS 26+)

func testSpeechAnalyzer() async {
    print("[SpeechAnalyzer] Starting...")

    let locale = Locale(identifier: "en-US")
    guard let supported = await SpeechTranscriber.supportedLocale(equivalentTo: locale) else {
        print("[SpeechAnalyzer] ERROR: en-US not supported")
        return
    }
    print("[SpeechAnalyzer] Locale supported: \(supported.identifier)")

    let transcriber = SpeechTranscriber(locale: supported, preset: .progressiveTranscription)

    // Ensure model
    if let request = try? await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
        print("[SpeechAnalyzer] Installing speech model...")
        try? await request.downloadAndInstall()
        print("[SpeechAnalyzer] Model installed")
    } else {
        print("[SpeechAnalyzer] Model already available")
    }

    let engine = AVAudioEngine()
    let inputNode = engine.inputNode
    let micFormat = inputNode.outputFormat(forBus: 0)
    print("[SpeechAnalyzer] Mic format: \(micFormat)")

    let targetFormat = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber])
    print("[SpeechAnalyzer] Target format: \(targetFormat?.description ?? "nil (will use mic format)")")

    // Build async stream
    let (inputStream, continuation) = AsyncStream.makeStream(of: AnalyzerInput.self)

    let analyzer = SpeechAnalyzer(modules: [transcriber])

    // Audio tap — try converter if needed, else raw
    var bufferCount = 0
    var convertedCount = 0
    var emptyCount = 0

    if let targetFormat = targetFormat, targetFormat != micFormat,
       let converter = AVAudioConverter(from: micFormat, to: targetFormat) {
        print("[SpeechAnalyzer] Using AVAudioConverter: \(micFormat.sampleRate)Hz → \(targetFormat.sampleRate)Hz")

        // Two-stage pipeline: capture raw, convert in async task
        let (rawStream, rawContinuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)

        inputNode.installTap(onBus: 0, bufferSize: 4096, format: micFormat) { buffer, _ in
            bufferCount += 1
            rawContinuation.yield(buffer)
        }

        // Converter task
        Task {
            for await rawBuffer in rawStream {
                let ratio = targetFormat.sampleRate / micFormat.sampleRate
                let capacity = AVAudioFrameCount(Double(rawBuffer.frameLength) * ratio)
                guard capacity > 0,
                      let converted = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else {
                    continue
                }

                var error: NSError?
                let status = converter.convert(to: converted, error: &error) { _, outStatus in
                    outStatus.pointee = .haveData
                    return rawBuffer
                }

                if status == .haveData && error == nil && converted.frameLength > 0 {
                    convertedCount += 1
                    continuation.yield(AnalyzerInput(buffer: converted))
                } else {
                    emptyCount += 1
                    if bufferCount <= 5 || emptyCount <= 3 {
                        print("[SpeechAnalyzer] Convert: status=\(status.rawValue) err=\(error?.localizedDescription ?? "nil") frames=\(converted.frameLength)")
                    }
                }
            }
            continuation.finish()
        }
    } else {
        print("[SpeechAnalyzer] No conversion needed — passing raw audio")
        inputNode.installTap(onBus: 0, bufferSize: 4096, format: micFormat) { buffer, _ in
            bufferCount += 1
            continuation.yield(AnalyzerInput(buffer: buffer))
        }
    }

    engine.prepare()
    do {
        try engine.start()
    } catch {
        print("[SpeechAnalyzer] ERROR starting engine: \(error)")
        return
    }

    // Result iteration task
    let resultTask = Task {
        print("[SpeechAnalyzer] Iterating transcriber.results...")
        do {
            for try await result in transcriber.results {
                let text = String(result.text.characters)
                let isFinal = result.isFinal
                print("[SpeechAnalyzer] \(isFinal ? "FINAL" : "partial"): \"\(text)\"")
            }
            print("[SpeechAnalyzer] Results stream ended naturally")
        } catch {
            print("[SpeechAnalyzer] Results error: \(error)")
        }
    }

    // Start analyzer
    do {
        print("[SpeechAnalyzer] Calling analyzer.start()...")
        try await analyzer.start(inputSequence: inputStream)
        print("[SpeechAnalyzer] analyzer.start() returned")
    } catch {
        print("[SpeechAnalyzer] ERROR in analyzer.start(): \(error)")
    }

    print("[SpeechAnalyzer] Listening for 8 seconds... speak now!")

    // Status prints every 2 seconds
    for i in 1...4 {
        try? await Task.sleep(for: .seconds(2))
        print("[SpeechAnalyzer] \(i*2)s — raw buffers: \(bufferCount), converted: \(convertedCount), empty: \(emptyCount)")
    }

    // Cleanup
    print("[SpeechAnalyzer] Stopping...")
    engine.stop()
    inputNode.removeTap(onBus: 0)
    continuation.finish()
    try? await analyzer.finalizeAndFinishThroughEndOfInput()
    resultTask.cancel()
    print("[SpeechAnalyzer] Done.")
}

// MARK: - Test 2: SFSpeechRecognizer (proven API)

func testSFSpeechRecognizer() {
    print("[SFSpeechRecognizer] Starting...")

    guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US")) else {
        print("[SFSpeechRecognizer] ERROR: Could not create recognizer")
        return
    }
    print("[SFSpeechRecognizer] Available: \(recognizer.isAvailable), supportsOnDevice: \(recognizer.supportsOnDeviceRecognition)")

    let engine = AVAudioEngine()
    let request = SFSpeechAudioBufferRecognitionRequest()
    request.shouldReportPartialResults = true
    request.requiresOnDeviceRecognition = true

    let inputNode = engine.inputNode
    let format = inputNode.outputFormat(forBus: 0)
    print("[SFSpeechRecognizer] Mic format: \(format)")

    var bufferCount = 0
    inputNode.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
        bufferCount += 1
        request.append(buffer)
    }

    engine.prepare()
    do {
        try engine.start()
    } catch {
        print("[SFSpeechRecognizer] ERROR starting engine: \(error)")
        return
    }

    print("[SFSpeechRecognizer] Listening for 8 seconds... speak now!")

    var gotResult = false
    let task = recognizer.recognitionTask(with: request) { result, error in
        if let result = result {
            gotResult = true
            let text = result.bestTranscription.formattedString
            let isFinal = result.isFinal
            print("[SFSpeechRecognizer] \(isFinal ? "FINAL" : "partial"): \"\(text)\"")
        }
        if let error = error {
            print("[SFSpeechRecognizer] Error: \(error.localizedDescription)")
        }
    }

    // Wait 8 seconds
    for i in 1...4 {
        Thread.sleep(forTimeInterval: 2.0)
        print("[SFSpeechRecognizer] \(i*2)s — buffers sent: \(bufferCount)")
    }

    // Cleanup
    print("[SFSpeechRecognizer] Stopping...")
    engine.stop()
    inputNode.removeTap(onBus: 0)
    request.endAudio()
    task.finish()

    // Give a moment for final result
    Thread.sleep(forTimeInterval: 1.0)
    if !gotResult {
        print("[SFSpeechRecognizer] No results received!")
    }
    print("[SFSpeechRecognizer] Done.")
}

// MARK: - Main

let mode = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "both"

// Request speech authorization
let authStatus = SFSpeechRecognizer.authorizationStatus()
print("Speech auth status: \(authStatus.rawValue) (0=notDetermined, 1=denied, 2=restricted, 3=authorized)")

if authStatus == .notDetermined {
    print("Requesting speech authorization...")
    await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
        SFSpeechRecognizer.requestAuthorization { status in
            print("Authorization result: \(status.rawValue)")
            cont.resume()
        }
    }
}

switch mode {
case "analyzer":
    await testSpeechAnalyzer()
case "recognizer":
    testSFSpeechRecognizer()
default:
    print("=== Testing SFSpeechRecognizer first (proven API) ===\n")
    testSFSpeechRecognizer()
    print("\n=== Testing SpeechAnalyzer (macOS 26+ async API) ===\n")
    await testSpeechAnalyzer()
}

print("\nAll tests complete.")
