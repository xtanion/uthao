const { withAppDelegate, withInfoPlist } = require('expo/config-plugins');

// iOS 27 traps at launch unless the app adopts the scene life cycle, and the
// SDK 57 template still starts React Native from the app delegate. Expo ships
// ExpoAppSceneDelegate for this; it only needs the app delegate to hand over
// its factory and the Info.plist to name it.

// Other plugins insert into this block (@react-native-firebase/app puts
// FirebaseApp.configure() right above startReactNative), so whatever sits
// between the window and the start is kept when the block goes.
const WINDOW_BLOCK =
  /\n#if os\(iOS\) \|\| os\(tvOS\)\n\s*window = UIWindow\(frame: UIScreen\.main\.bounds\)\n([\s\S]*?)\s*factory\.startReactNative\([\s\S]*?\)\n#endif\n/;

const withSceneAppDelegate = (config) =>
  withAppDelegate(config, (config) => {
    let src = config.modResults.contents;
    if (src.includes('ExpoReactNativeFactoryProvider')) return config;
    if (!WINDOW_BLOCK.test(src) || !src.includes('class AppDelegate: ExpoAppDelegate {')) {
      throw new Error('withSceneLifecycle: AppDelegate.swift no longer matches the expected template');
    }
    src = src
      .replace('class AppDelegate: ExpoAppDelegate {', 'class AppDelegate: ExpoAppDelegate, ExpoReactNativeFactoryProvider {')
      .replace(WINDOW_BLOCK, (_, kept) => (kept ? `\n${kept}\n` : '\n'));
    config.modResults.contents = src;
    return config;
  });

const withSceneManifest = (config) =>
  withInfoPlist(config, (config) => {
    config.modResults.UIApplicationSceneManifest = {
      UIApplicationSupportsMultipleScenes: false,
      UISceneConfigurations: {
        UIWindowSceneSessionRoleApplication: [
          {
            UISceneConfigurationName: 'Default Configuration',
            UISceneDelegateClassName: 'EXExpoAppSceneDelegate',
          },
        ],
      },
    };
    return config;
  });

module.exports = (config) => withSceneManifest(withSceneAppDelegate(config));
