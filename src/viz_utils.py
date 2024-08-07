import torch
import cv2
import numpy as np
import matplotlib.pyplot as plt
import wandb
import os
from typing import Optional

RED = np.array([1, 0, 0])
GREEN = np.array([0, 1, 0])
BLUE = np.array([0, 0, 1])
CYAN = np.array([0, 1, 1])
YELLOW = np.array([1, 1, 0])
MAGENTA = np.array([1, 0, 1])


# taken from https://github.com/robodhruv/visualnav-transformer/blob/7b5b24cf12d0989fb5b5ff378d5630dd737eec3b/train/vint_train/visualizing/action_utils.py
def plot_trajs_and_points(
        ax: plt.Axes,
        list_trajs: list,
        list_points: list,
        traj_colors: list = [CYAN, MAGENTA],
        point_colors: list = [RED, GREEN],
        traj_labels: Optional[list] = ["prediction", "ground truth"],
        point_labels: Optional[list] = ["robot", "goal"],
        traj_alphas: Optional[list] = None,
        point_alphas: Optional[list] = None,
        frame_dir: str = "images/frames",
        quiver_freq: int = 1,
        default_coloring: bool = True,
):
    """
    Plot trajectories and points that could potentially have a yaw.

    Args:
        ax: matplotlib axis
        list_trajs: list of trajectories, each trajectory is a numpy array of shape (horizon, 2) (if there is no yaw) or (horizon, 4) (if there is yaw)
        list_points: list of points, each point is a numpy array of shape (2,)
        traj_colors: list of colors for trajectories
        point_colors: list of colors for points
        traj_labels: list of labels for trajectories
        point_labels: list of labels for points
        traj_alphas: list of alphas for trajectories
        point_alphas: list of alphas for points
        frame_dir: frame directory to save for GIF
        quiver_freq: frequency of quiver plot (if the trajectory data includes the yaw of the robot)
    """
    assert (
            len(list_trajs) <= len(traj_colors) or default_coloring
    ), "Not enough colors for trajectories"
    assert len(list_points) <= len(point_colors), "Not enough colors for points"
    assert (
            traj_labels is None or len(list_trajs) == len(traj_labels) or default_coloring
    ), "Not enough labels for trajectories"
    assert point_labels is None or len(list_points) == len(point_labels), "Not enough labels for points"

    for i, traj in enumerate(list_trajs):
        if traj_labels is None:
            ax.plot(
                traj[:, 0],
                traj[:, 1],
                color=traj_colors[i],
                alpha=traj_alphas[i] if traj_alphas is not None else 1.0,
                marker="o",
                linestyle="-",
            )
        else:
            ax.plot(
                traj[:, 0],
                traj[:, 1],
                color=traj_colors[i],
                label=traj_labels[i],
                alpha=traj_alphas[i] if traj_alphas is not None else 1.0,
                marker="o",
                linestyle="-",
            )

            # plt.title(f"Frame {i}")
            # plt.savefig(os.path.join(frame_dir, f"frame_{i:03d}.png"))

        if traj.shape[1] > 2 and quiver_freq > 0:  # traj data also includes yaw of the robot
            bearings = gen_bearings_from_waypoints(traj)
            ax.quiver(
                traj[::quiver_freq, 0],
                traj[::quiver_freq, 1],
                bearings[::quiver_freq, 0],
                bearings[::quiver_freq, 1],
                color=traj_colors[i] * 0.5,
                scale=1.0,
            )
    for i, pt in enumerate(list_points):
        if point_labels is None:
            ax.plot(
                pt[0],
                pt[1],
                color=point_colors[i],
                alpha=point_alphas[i] if point_alphas is not None else 1.0,
                marker="o",
                markersize=7.0,
                linestyle="-",
            )
        else:
            ax.plot(
                pt[0],
                pt[1],
                color=point_colors[i],
                alpha=point_alphas[i] if point_alphas is not None else 1.0,
                marker="o",
                markersize=7.0,
                label=point_labels[i],
                linestyle="-",
            )

    # put the legend below the plot
    if traj_labels is not None or point_labels is not None:
        ax.legend()
        ax.legend(bbox_to_anchor=(0.0, -0.5), loc="upper left", ncol=2)
    ax.set_aspect("equal", "box")


def generate_masks(viz_obs: torch.Tensor, model) -> dict:
    viz_obs = np.moveaxis(to_numpy(viz_obs), 0, -1)
    viz_obs = (viz_obs * 255.).astype("uint8")
    return model.generate(viz_obs)


def mask_to_img(masks: dict) -> np.ndarray:
    """
    Converts a binary mask to a randomized-color RGB image.
    """

    sorted_anns = sorted(masks, key=(lambda x: x['area']), reverse=True)
    mask_img = np.ones((masks[0]['segmentation'].shape[0], masks[0]['segmentation'].shape[1], 3))
    for ann in sorted_anns:
        m = ann['segmentation']
        mask_img[m] = np.random.random(3)

    mask_img = cv2.resize(mask_img, (256, 256))  # TODO: for ViT, it will be distorted
    mask_img = np.resize(mask_img, (mask_img.shape[-1], mask_img.shape[0], mask_img.shape[1]))

    mask_img = torch.from_numpy(mask_img).unsqueeze(0)
    mask_img = mask_img.to(torch.float32)  # type incompatibility otherwise

    # print("mask img shape ===", mask_img.shape)

    return mask_img  # Mobile-ViT only takes scalar doubles


def visualize_sam_maps(
        viz_obs: torch.Tensor,
        viz_goal: torch.Tensor,
        obs_map: dict,
        goal_map: dict,
        viz_freq: int = 10,
):
    def show_anns(anns, ax):
        if len(anns) == 0:
            return

        sorted_anns = sorted(anns, key=(lambda x: x['area']), reverse=True)
        ax.set_autoscale_on(True)

        img = np.ones((sorted_anns[0]['segmentation'].shape[0], sorted_anns[0]['segmentation'].shape[1], 4))
        img[:, :, 3] = 0
        for ann in sorted_anns:
            m = ann['segmentation']
            color_mask = np.concatenate([np.random.random(3), [0.35]])
            img[m] = color_mask
        ax.imshow(img)

    wandb_list = []

    for i, (obs, goal) in enumerate(zip(batch_viz_obs_images, batch_viz_goal_images)):
        if i % viz_freq == 0:
            fig, ax = plt.subplots(1, 4)

            obs_img = np.moveaxis(to_numpy(obs), 0, -1)
            goal_img = np.moveaxis(to_numpy(goal), 0, -1)

            obs_img = (obs_img * 255.).astype('uint8')
            goal_img = (goal_img * 255.).astype('uint8')

            ax[0].imshow(obs_img)
            ax[1].imshow(goal_img)

            # save_path = os.path.join(visualize_path, 'original.png')
            # plt.savefig(save_path)
            # wandb_list.append(wandb.Image(save_path))
            # wandb.log({'examples': wandb_list}, commit=False)

            # generate masks
            # obs_map = mask_generator.generate(obs_img)
            # goal_map = mask_generator.generate(goal_img)

            # ax[2].imshow(obs_map['segmentation'])
            # ax[3].imshow(goal_map['segmentation'])

            # show_anns(obs_map, ax[0])
            # show_anns(goal_map, ax[1])

            show_anns(obs_map, ax[2])
            show_anns(goal_map, ax[3])

            ax[0].set_title('Observation')
            ax[1].set_title('Goal')
            ax[2].set_title('Obs Map')
            ax[3].set_title('Goal Map')

            for a in ax.flatten():
                a.axis('off')

            visualize_path = "examples"
            map_save_path = os.path.join(visualize_path, f'maps_{i}.png')
            plt.savefig(map_save_path)

            wandb_list.append(wandb.Image(map_save_path))

            wandb.log({'examples': wandb_list}, commit=False)

            print(f"Finished generating masks for maps_{i}.png.")


# IOU conversion
# map_ious = [obs["predicted_iou"] for obs in obs_map]
# avg_iou = sum(map_ious) / len(map_ious)

# o = stlcg.Expression('obs', obs)
# g = stlcg.Expression('g', goal)

# intersection = (obs & goal).float().sum((1, 2)) + 1e-6
# union = (obs | goal).float().sum(i(1, 2)) + 1e-6
# iou = intersection / union
# iou = avg_iou * 2. - 1.  # without normalization set to >.5


# class STLViz:
#     def __init__(
#         self,
#         unshuffled_dataset: torch.utils.data.DataLoader
#     ):
#         self.formula = self.generate_waypoints(unshuffled_dataset)
#
#         # specify ViT mask generators
#         weight_path = os.path.join(os.getcwd(), "pre_trained_weights/weights/weight/sam_vit_h_4b8939.pth")
#         model_type = 'vit_h'
#         mobile_sam = sam_model_registry[model_type](checkpoint=weight_path).to(device=device).eval()
#         self.mask_generator = SamAutomaticMaskGenerator(mobile_sam)
#
#         # specify ViT image encoder
#         mbvit_xs = MobileViT(
#                 image_size=mbvit_config['image_size'],
#                 dims=mbvit_config['dims'],
#                 channel=mbvit_config['channel'],
#                 num_classes=mbvit_config['num_classes'],
#         )
#
#     def generate_masks(obs_img: torch.Tensor):
#         return self.mask_generator.generate(obs_img)
#
#     def generate_waypoints(self, dataset) -> stlcg.STL_Formula:
#         for i, data in enumerate(tqdm.tqdm(dataset, desc="Generating waypoints...")):
#             obs_img, goal_img, _, _, _, _, _ = data
#
#             obs_imgs = torch.split(obs_img, 3, dim=1)
#             viz_obs_img = TF.resize(obs_imgs[-1], VISUALIZATION_IMAGE_SIZE[::-1])
#
#             #map_ious = [obs["predicted_iou"] for obs in obs_map]
#             #avg_iou = sum(map_ious) / len(map_ious)
#
#             #o = stlcg.Expression('obs', obs)
#             #g = stlcg.Expression('g', goal)
#
#             #intersection = (obs & goal).float().sum((1, 2)) + 1e-6
#             #union = (obs | goal).float().sum(i(1, 2)) + 1e-6
#             #iou = intersection / union
#             #iou = avg_iou * 2. - 1.  # without normalization set to >.5
#
#             #return stlcg.Always(stlcg.Expression('iou', iou))
#
#
#
#     def compute_stl_loss(self, viz_obs: torch.Tensor) -> dict, torch.Tensor:
#         stl_loss = 0
#
#         for i, obs in enumerate(viz_obs):
#             obs = np.moveaxis(obs, 0, -1)
#             obs = (obs * 255.).astype("uint8")
#             obs_map = self.mask_generator(obs)
#
#             margin = 0.05
#
#             # STL loss
#             if self.formula is None:
#                 raise ValueError(f"Formula is not properly defined: {self.formula}")
#
#             robustness = (-self.formula.robustness(obs_map)).squeeze()
#             stl_loss += F.leaky_relu(robustness - margin).mean()
#
#         return stl_loss / viz_obs.shape[0]  # TODO: check if this is right
#
#     @staticmethod
#     def visualize_sam_maps(
#         viz_obs: torch.Tensor,
#         viz_goal: torch.Tensor,
#         obs_map: dict,
#         goal_map: dict,
#         viz_freq: int = 10,
#     ):
#
#         def show_anns(anns, ax):
#             if len(anns) == 0:
#                 return
#
#             sorted_anns = sorted(anns, key=(lambda x: x['area']), reverse=True)
#             ax.set_autoscale_on(True)
#
#             img = np.ones((sorted_anns[0]['segmentation'].shape[0], sorted_anns[0]['segmentation'].shape[1], 4))
#             img[:,:,3] = 0
#             for ann in sorted_anns:
#                 m = ann['segmentation']
#                 color_mask = np.concatenate([np.random.random(3), [0.35]])
#                 img[m] = color_mask
#             ax.imshow(img)
#
#         wandb_list = []
#
#         for i, (obs, goal) in enumerate(zip(batch_viz_obs_images, batch_viz_goal_images)):
#             if i % viz_freq == 0:
#                 fig, ax = plt.subplots(1, 4)
#
#                 obs_img = np.moveaxis(to_numpy(obs), 0, -1)
#                 goal_img = np.moveaxis(to_numpy(goal), 0, -1)
#
#                 obs_img = (obs_img * 255.).astype('uint8')
#                 goal_img = (goal_img * 255.).astype('uint8')
#
#                 ax[0].imshow(obs_img)
#                 ax[1].imshow(goal_img)
#
#                 #save_path = os.path.join(visualize_path, 'original.png')
#                 #plt.savefig(save_path)
#                 #wandb_list.append(wandb.Image(save_path))
#                 #wandb.log({'examples': wandb_list}, commit=False)
#
#                 # generate masks
#                 # obs_map = mask_generator.generate(obs_img)
#                 # goal_map = mask_generator.generate(goal_img)
#
#                 #ax[2].imshow(obs_map['segmentation'])
#                 #ax[3].imshow(goal_map['segmentation'])
#
#                 #show_anns(obs_map, ax[0])
#                 #show_anns(goal_map, ax[1])
#
#                 show_anns(obs_map, ax[2])
#                 show_anns(goal_map, ax[3])
#
#                 ax[0].set_title('Observation')
#                 ax[1].set_title('Goal')
#                 ax[2].set_title('Obs Map')
#                 ax[3].set_title('Goal Map')
#
#                 for a in ax.flatten():
#                     a.axis('off')
#
#                 map_save_path = os.path.join(visualize_path, f'maps_{i}.png')
#                 plt.savefig(map_save_path)
#
#                 wandb_list.append(wandb.Image(map_save_path))
#
#                 wandb.log({'examples': wandb_list}, commit=False)
#
#                 print(f"Finished generating masks for maps_{i}.png.")
