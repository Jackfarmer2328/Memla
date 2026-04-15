import Foundation
import AppIntents

struct ScoutIntent: AppIntent {
    static var title: LocalizedStringResource = "Scout with Memla"
    static var description = IntentDescription("Run a bounded Memla scout request against the Mac-hosted local runtime.")

    @Parameter(title: "Goal")
    var goal: String

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let baseURL = UserDefaults.standard.string(forKey: "memlaBaseURL") ?? "http://192.168.1.10:8080"
        let result = try await MemlaClient.shared.scout(prompt: goal, baseURL: baseURL)
        return .result(value: result.result.summary)
    }
}
