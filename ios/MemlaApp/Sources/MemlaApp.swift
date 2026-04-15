import SwiftUI

@main
struct MemlaApp: App {
    @StateObject private var viewModel = MemlaViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(viewModel)
        }
    }
}
