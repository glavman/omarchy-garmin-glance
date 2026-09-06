pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui as Ui
import "Setup.js" as Guide

FocusScope {
  id: root
  property var service: null
  property bool expanded: false
  property bool copied: false
  readonly property bool demo: !!service && service.demoMode
  signal openedGuide()
  signal dismissed()
  signal focusMoved(var item)
  signal scrollRequested(int direction, bool page)
  implicitHeight: content.implicitHeight

  function open() {
    expanded = true
    copied = false
    openedGuide()
    copyButton.forceActiveFocus()
  }
  function dismiss() {
    expanded = false
    copied = false
    dismissed()
  }
  Keys.onEscapePressed: function(event) { dismiss(); event.accepted = true }
  Keys.onPressed: function(event) {
    if (!expanded) return
    var direction = event.key === Qt.Key_Down || event.key === Qt.Key_PageDown ? 1
      : event.key === Qt.Key_Up || event.key === Qt.Key_PageUp ? -1 : 0
    if (!direction) return
    scrollRequested(direction, event.key === Qt.Key_PageDown || event.key === Qt.Key_PageUp)
    event.accepted = true
  }

  component GuideText: Text {
    width: parent.width; textFormat: Text.PlainText; wrapMode: Text.Wrap
    color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body
  }
  component GuideButton: Ui.Button {
    id: button
    focusable: true; bordered: true
    width: Math.min(implicitWidth, parent.width)
    foreground: Color.popups.text
    onActiveFocusChanged: if (activeFocus) root.focusMoved(button)
  }

  Column {
    id: content
    width: parent.width; spacing: Style.space(10)
    GuideText {
      visible: root.demo
      text: "Explore synthetic demo data. No database is queried; Coach and activity links are disabled."
    }
    GuideButton {
      objectName: "setupEntry"
      text: root.expanded ? "Close setup" : "Set up live data (S)"
      onClicked: root.expanded ? root.dismiss() : root.open()
    }
    Column {
      visible: root.expanded
      width: parent.width; spacing: Style.space(10)
      GuideText { text: "CONNECT YOUR GARMIN DATA"; font.bold: true }
      GuideText {
        text: "1. Use an existing garmin-grafana stack with InfluxDB 1.x. The collector handles Garmin sign-in and sync; this plugin reads its database, not the Grafana API."
      }
      GuideText {
        text: "2. Copy this prompt into your Omarchy agent, or follow the manual guide. Get approval and disable this plugin before preparing or replacing connection config: automatic refresh can query as soon as a valid file exists. Use a dedicated READ-only database account and keep credentials out of chat. Nothing is launched automatically."
      }
      GuideButton {
        id: copyButton
        objectName: "setupCopy"
        text: root.copied ? "Prompt copied" : "Copy setup prompt"
        onClicked: { promptText.selectAll(); promptText.copy(); promptText.deselect(); root.copied = true }
      }
      TextEdit {
        id: promptText
        objectName: "setupPrompt"
        width: parent.width
        text: Guide.prompt; textFormat: TextEdit.PlainText
        readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
        color: Color.popups.text; selectionColor: Color.popups.text; selectedTextColor: Color.popups.background
        font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
        Accessible.name: "Agent setup prompt"
        onActiveFocusChanged: if (activeFocus) root.focusMoved(promptText)
      }
      GuideButton {
        objectName: "setupDocs"
        text: "Open setup guide"
        onClicked: Qt.openUrlExternally(Guide.documentationUrl)
      }
      GuideText {
        text: "3. Keep the plugin disabled while configuring ~/.config/omarchy-garmin-glance/connection.json. Verify enforced authentication, non-admin READ-only grants and doctor as described in the guide. Then enable and refresh to load live data. Do not add an already installed plugin again."
      }
      GuideText {
        visible: root.demo && !!root.service && root.service.requestedDemoMode === true
        text: "Synthetic demo data is explicitly enabled in widget settings. Turn it off after setup, then refresh."
      }
      GuideButton {
        objectName: "setupRefresh"
        text: "Refresh connection"; enabled: !!root.service && !root.service.busy
        onClicked: root.service.refresh(true)
      }
      GuideText {
        text: "Tab / Shift-Tab: setup controls. Up / Down or Page Up / Page Down: scroll. Escape: return to dashboard."
        opacity: 0.65
      }
    }
  }
}
