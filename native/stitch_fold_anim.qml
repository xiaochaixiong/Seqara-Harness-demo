import QtQuick

// 与 StitchFoldController._load_fold_qml_or_raise 注入的 context 属性配合：
// foldBridge.clipHeight、foldCtl.playExpand/playCollapse/stopAll、foldDriver.expandDone/collapseDone、foldExpandMs/foldCollapseMs
// 根须用 Item（有默认 data 子属性）；QtObject 无默认子属性，嵌 Connections 会报「Cannot assign to non-existent default property」。
Item {
    id: root
    width: 0
    height: 0
    visible: false

    Connections {
        target: foldCtl

        function onPlayExpand(targetH) {
            expandAnim.stop()
            collapseAnim.stop()
            foldBridge.clipHeight = 0
            expandAnim.from = 0
            expandAnim.to = targetH
            expandAnim.duration = foldExpandMs
            expandAnim.start()
        }

        function onPlayCollapse(startH) {
            expandAnim.stop()
            collapseAnim.stop()
            foldBridge.clipHeight = startH
            collapseAnim.from = startH
            collapseAnim.to = 0
            collapseAnim.duration = foldCollapseMs
            collapseAnim.start()
        }

        function onStopAll() {
            expandAnim.stop()
            collapseAnim.stop()
        }
    }

    NumberAnimation {
        id: expandAnim
        target: foldBridge
        property: "clipHeight"
        easing.type: Easing.OutQuint
        onFinished: foldDriver.expandDone()
    }

    NumberAnimation {
        id: collapseAnim
        target: foldBridge
        property: "clipHeight"
        easing.type: Easing.InOutCubic
        onFinished: foldDriver.collapseDone()
    }
}
